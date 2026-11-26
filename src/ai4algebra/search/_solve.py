"""Bounded proof search over immutable Lean observations."""

import heapq
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event
from typing import Protocol
from uuid import uuid4

from ai4algebra.candidates import GenerationResult
from ai4algebra.config import Limits
from ai4algebra.contracts import (
    Candidate,
    CandidateSet,
    Certificate,
    Observation,
    Problem,
    Snapshot,
    StepResult,
    Transition,
    Verdict,
    digest_json,
)
from ai4algebra.lean_bridge import Bridge, BridgeError, BridgeTimeout, LeanBridge
from ai4algebra.learning import CollectedSample, EncodedDecision, encode_decision
from ai4algebra.representation import DecisionContext, FeatureEncoder
from ai4algebra.verification import EligibilityPolicy, Verifier

from ._policy import ActionPolicy, Choice, Decision, DeterministicPolicy
from ._records import (
    Attempt,
    BudgetReason,
    GenerationTrace,
    ProbeTrace,
    ProofNode,
    SearchMode,
    SearchOptions,
    SearchReport,
    SearchStatus,
    Work,
)


class Generator(Protocol):
    def generate(
        self,
        snapshot: Snapshot,
        observation: Observation,
        limits: Limits,
        *,
        probe_limit: int | None = None,
        timeout_seconds: float | None = None,
        attempted: frozenset[str] = frozenset(),
        cancelled: Event | None = None,
        stop_on_closure: bool = False,
    ) -> GenerationResult: ...


class ProofVerifier(Protocol):
    def build_certificate(
        self,
        problem: Problem,
        steps: tuple[Candidate, ...],
        eligibility: EligibilityPolicy,
    ) -> Certificate: ...

    def verify(
        self,
        problem: Problem,
        certificate: Certificate,
        eligibility: EligibilityPolicy,
        *,
        timeout_seconds: float | None = None,
    ) -> Verdict: ...


@dataclass
class _Entry:
    node: ProofNode
    steps: tuple[Candidate, ...]
    generated: GenerationResult | None = None
    attempted: set[str] = field(default_factory=set)
    expanded: bool = False
    probe_calls: int = 0


class _Run:
    def __init__(
        self,
        problem: Problem,
        eligibility: EligibilityPolicy,
        policy: ActionPolicy,
        bridge: Bridge,
        generator: Generator,
        verifier: ProofVerifier,
        limits: Limits,
        options: SearchOptions,
        mode: SearchMode,
        encoder: FeatureEncoder | None,
        episode_id: str,
        collection_step: int,
        clock: Callable[[], float],
        cancelled: Event,
    ) -> None:
        self.problem = problem
        self.eligibility = eligibility
        self.policy = policy
        self.bridge = bridge
        self.generator = generator
        self.verifier = verifier
        self.limits = limits
        self.options = options
        self.mode = mode
        self.training = mode == "rollout" and problem.split == "train"
        self.encoder = encoder
        self.episode_id = episode_id
        self.collection_step = collection_step
        self.clock = clock
        self.cancelled = cancelled
        self.started = clock()
        self.deadline = self.started + limits.task_timeout_seconds
        self.verification_reserve = min(
            options.verification_reserve_seconds
            or min(limits.step_timeout_seconds, limits.task_timeout_seconds / 4),
            limits.task_timeout_seconds / 2,
        )
        self.continuation_probe_reserve = (
            min(options.continuation_probes, limits.max_steps - 1)
            if self.training
            else 0
        )
        self.continuation_reserve = (
            min(
                options.continuation_reserve_seconds
                or min(limits.step_timeout_seconds, limits.task_timeout_seconds / 8),
                limits.task_timeout_seconds / 4,
            )
            if self.continuation_probe_reserve
            else 0.0
        )
        self.work: dict[str, int] = {}
        self.budgets: dict[BudgetReason, None] = {}
        self.nodes: dict[str, ProofNode] = {}
        self.frontier: list[tuple[tuple[int, int, int], _Entry]] = []
        self.generations: list[GenerationTrace] = []
        self.attempts: list[Attempt] = []
        self.samples: list[CollectedSample] = []
        self.diagnostics: list[str] = []
        self.last_observation: Observation | None = None
        self.final_candidate_set: CandidateSet | None = None
        self.pending: Attempt | None = None
        self.accepted: Attempt | None = None
        self.infra_reason: str | None = None
        self.audit_rejected = False

    def _count(self, metric: str, amount: int = 1) -> None:
        self.work[metric] = self.work.get(metric, 0) + amount

    def _remaining_steps(self) -> int:
        return (
            self.limits.max_steps
            - self.work.get("probe_calls", 0)
            - self.work.get("action_calls", 0)
        )

    def _remaining_time(self, *, continuation: bool = False) -> float:
        reserve = self.verification_reserve
        if not continuation:
            reserve += self.continuation_reserve
        return max(0.0, self.deadline - self.clock() - reserve)

    def _remember(
        self, observation: Observation, candidate_set: CandidateSet | None = None
    ) -> None:
        self.last_observation = observation
        self.final_candidate_set = candidate_set

    def _new_node(
        self,
        observation: Observation,
        parent: _Entry | None,
        candidate: Candidate | None,
    ) -> _Entry:
        steps = (
            () if parent is None or candidate is None else (*parent.steps, candidate)
        )
        repeated = None
        ancestor = None if parent is None else parent.node
        while ancestor is not None:
            if observation.goals == ancestor.observation.goals:
                # Equal exposed goals can conceal different metavariable assignments.
                # Record a repeat without merging branches or discarding a proof prefix.
                repeated = ancestor.node_id
                break
            ancestor = (
                None if ancestor.parent_id is None else self.nodes[ancestor.parent_id]
            )
        node = ProofNode(
            node_id=f"n{len(self.nodes)}",
            parent_id=None if parent is None else parent.node.node_id,
            incoming_candidate=candidate,
            statement_digest=self.problem.statement_digest,
            depth=len(steps),
            observation=observation,
            repeated_node_id=repeated,
        )
        self.nodes[node.node_id] = node
        return _Entry(node, steps)

    def _push(self, entry: _Entry) -> None:
        if self.mode == "best_first":
            node = entry.node
            priority = (node.depth, len(node.observation.goals), int(node.node_id[1:]))
            heapq.heappush(self.frontier, (priority, entry))
        else:
            self.frontier.append(((0, 0, 0), entry))

    def _pop(self) -> _Entry:
        if self.mode == "best_first":
            return heapq.heappop(self.frontier)[1]
        return self.frontier.pop()[1]

    def _cutoff(self, entry: _Entry) -> BudgetReason | None:
        if self.cancelled.is_set():
            return "cancelled"
        if entry.node.depth >= self.limits.max_depth:
            return "depth"
        if entry.generated is not None:
            # Applicability may have already paid for the last legal step.
            return "time" if self.clock() >= self.deadline else None
        if (
            not entry.expanded
            and self.work.get("nodes_expanded", 0) >= self.limits.max_nodes
        ):
            return "nodes"
        if self._remaining_steps() <= self.continuation_probe_reserve:
            return "steps"
        if self._remaining_time() <= 0:
            return "time"
        return None

    def _generate(self, entry: _Entry, *, continuation: bool) -> None:
        remaining = self._remaining_steps()
        bound = (
            min(self.continuation_probe_reserve, remaining)
            if continuation
            else remaining - self.continuation_probe_reserve
        )
        probe_cap = self.options.probes_per_node or self.limits.max_candidates
        budget = min(bound, probe_cap - entry.probe_calls)
        timeout = self._remaining_time(continuation=continuation)
        if budget <= 0 or timeout <= 0 or self.cancelled.is_set():
            if not continuation:
                reason: BudgetReason = (
                    "cancelled"
                    if self.cancelled.is_set()
                    else "time"
                    if timeout <= 0
                    else "steps"
                    if bound <= 0
                    else "probe_limit"
                )
                self.budgets[reason] = None
            return
        self._count("generation_calls")
        if continuation:
            self._count("continuation_generations")
        elif not entry.expanded:
            self._count("nodes_expanded")
            entry.expanded = True
        observation = entry.node.observation
        stop_on_closure = self.options.stop_on_closure and not continuation
        try:
            generated = self.generator.generate(
                observation.snapshot,
                observation,
                self.limits,
                probe_limit=budget,
                timeout_seconds=timeout,
                attempted=frozenset(entry.attempted),
                cancelled=self.cancelled,
                stop_on_closure=stop_on_closure,
            )
        except BridgeTimeout as exc:
            self.budgets["step_timeout"] = None
            self.diagnostics.append(str(exc))
            return
        except BridgeError as exc:
            self.infra_reason = "candidate_infrastructure"
            self.diagnostics.append(str(exc))
            return
        if not 0 <= generated.recovery_calls <= generated.probe_calls <= budget:
            raise BridgeError("candidate generator exceeded the requested probe budget")
        self._count("probe_calls", generated.probe_calls)
        self._count("recovery_calls", generated.recovery_calls)
        entry.probe_calls += generated.probe_calls
        self._count("provider_requests", generated.provider_requests)
        self._count("token_count_requests", generated.token_count_requests)
        candidate_set = generated.candidate_set
        try:
            candidate_set.validate_for(observation)
            if candidate_set.policy_digest != self.eligibility.policy_digest:
                raise ValueError(
                    "candidate generator returned a different eligibility policy"
                )
            if len(candidate_set.candidates) > self.limits.max_candidates:
                raise ValueError(
                    "candidate generator exceeded the requested candidate budget"
                )
            self.eligibility.validate_for(
                self.problem,
                tuple(
                    candidate
                    for candidate, legal in zip(
                        candidate_set.candidates, candidate_set.eligible, strict=True
                    )
                    if legal
                ),
            )
        except ValueError as exc:
            self.infra_reason = "candidate_infrastructure"
            self.diagnostics.append(str(exc))
            return
        entry.generated = generated
        self.generations.append(
            GenerationTrace(
                retrieved_premises=generated.retrieved_premises,
                node_id=entry.node.node_id,
                candidate_set=candidate_set,
                probes=tuple(
                    ProbeTrace(
                        candidate_id=probe.candidate_id,
                        status=probe.status,
                        reused=probe.reused,
                        result=probe.result,
                    )
                    for probe in generated.probes
                ),
                provider_status=generated.provider_status,
                provider_requests=generated.provider_requests,
                token_count_requests=generated.token_count_requests,
                probe_calls=generated.probe_calls,
                recovery_calls=generated.recovery_calls,
                probe_limit=budget,
                timeout_seconds=timeout,
                stop_on_closure=stop_on_closure,
                stopped_after_closure=generated.stopped_after_closure,
                continuation=continuation,
            )
        )
        if candidate_set.generation_status == "unavailable":
            self.infra_reason = "candidate_infrastructure"
        if candidate_set.generation_status == "budget_exhausted":
            if any(probe.status == "timeout" for probe in generated.probes):
                self.budgets["step_timeout"] = None
            if self._remaining_steps() <= (
                0 if continuation else self.continuation_probe_reserve
            ):
                self.budgets["steps"] = None
            elif self._remaining_time(continuation=continuation) <= 0:
                self.budgets["time"] = None
            elif any(probe.status == "not_probed" for probe in generated.probes):
                self.budgets["probe_limit"] = None

    @staticmethod
    def _available(entry: _Entry, candidate_set: CandidateSet) -> CandidateSet:
        eligible = tuple(
            legal and candidate.candidate_id not in entry.attempted
            for candidate, legal in zip(
                candidate_set.candidates, candidate_set.eligible, strict=True
            )
        )
        if eligible != candidate_set.eligible:
            return candidate_set.model_copy(update={"eligible": eligible})
        return candidate_set

    def _decision(self, entry: _Entry) -> Decision | None:
        generated = entry.generated
        if generated is None:
            return None
        observation = entry.node.observation
        candidate_set = self._available(entry, generated.candidate_set)
        self._remember(observation, candidate_set)
        if not any(candidate_set.eligible):
            return None
        encoded = None
        if self.encoder is not None:
            encoded = encode_decision(
                self.encoder,
                observation,
                candidate_set,
                DecisionContext(
                    remaining_depth=self.limits.max_depth - entry.node.depth,
                    remaining_steps=self._remaining_steps(),
                    eligible_count=sum(candidate_set.eligible),
                ),
                candidate_contexts=generated.candidate_contexts,
            )
        return Decision(
            observation,
            candidate_set,
            encoded,
            self.episode_id,
            self.collection_step + len(self.attempts),
        )

    def _apply(
        self, entry: _Entry, candidate: Candidate
    ) -> tuple[StepResult, bool] | None:
        if self.cancelled.is_set():
            self.budgets["cancelled"] = None
            return None
        generated = entry.generated
        assert generated is not None
        probe = next(
            (
                probe
                for probe in generated.probes
                if probe.candidate_id == candidate.candidate_id
            ),
            None,
        )
        if probe is not None and probe.eligible and probe.result is not None:
            if probe.status != probe.result.status:
                raise BridgeError(
                    "applicability status differs from the stored step result"
                )
            self._count("reused_probes")
            return probe.result, True
        remaining = self._remaining_time()
        remaining_requests = self._remaining_steps() - self.continuation_probe_reserve
        if remaining_requests <= 0:
            self.budgets["steps"] = None
            return None
        if remaining <= 0:
            self.budgets["time"] = None
            return None
        try:
            snapshot = self.bridge.fork(entry.node.observation.snapshot)
            if snapshot != entry.node.observation.snapshot:
                raise BridgeError("fork did not preserve the parent snapshot")
            if isinstance(self.bridge, LeanBridge):
                result, usage = self.bridge.step_with_usage(
                    snapshot,
                    candidate,
                    timeout_seconds=remaining,
                    max_worker_requests=remaining_requests,
                    cancelled=self.cancelled,
                )
                self._count("action_calls", usage.worker_requests)
                self._count("recovery_calls", usage.recovery_requests)
                return result, False
            self._count("action_calls")
            return self.bridge.step(snapshot, candidate), False
        except BridgeTimeout as exc:
            return StepResult(status="timeout", diagnostics=(str(exc),)), False
        except BridgeError as exc:
            return StepResult(
                status="infrastructure_error", diagnostics=(str(exc),)
            ), False

    def _audit(self, entry: _Entry) -> tuple[str, Certificate | None, Verdict | None]:
        if self.cancelled.is_set():
            self.budgets["cancelled"] = None
            return "audit_cancelled", None, None
        if self.clock() >= self.deadline:
            self.budgets["time"] = None
            return "audit_budget", None, None
        certificate = None
        try:
            certificate = self.verifier.build_certificate(
                self.problem, entry.steps, self.eligibility
            )
            if (
                certificate.steps != entry.steps
                or certificate.task_id != self.problem.task_id
                or certificate.statement_digest != self.problem.statement_digest
                or certificate.source_digest != self.problem.source.content_digest
                or certificate.imports != self.problem.imports
                or certificate.environment_digest
                != entry.node.observation.snapshot.environment_digest
                or certificate.policy_digest != self.eligibility.policy_digest
                or certificate.eligibility_digest != self.eligibility.eligibility_digest
            ):
                raise BridgeError(
                    "certificate does not identify the selected proof branch"
                )
            remaining = self.deadline - self.clock()
            if self.cancelled.is_set():
                self.budgets["cancelled"] = None
                return "audit_cancelled", certificate, None
            if remaining <= 0:
                self.budgets["time"] = None
                return "audit_budget", certificate, None
            self._count("verifier_calls")
            if isinstance(self.verifier, Verifier):
                verdict = self.verifier.verify(
                    self.problem,
                    certificate,
                    self.eligibility,
                    timeout_seconds=remaining,
                    cancelled=self.cancelled,
                )
            else:
                verdict = self.verifier.verify(
                    self.problem,
                    certificate,
                    self.eligibility,
                    timeout_seconds=remaining,
                )
        except (BridgeError, ValueError) as exc:
            self.diagnostics.append(str(exc))
            if self.cancelled.is_set():
                self.budgets["cancelled"] = None
                return "audit_cancelled", certificate, None
            if isinstance(exc, ValueError):
                self.audit_rejected = True
                return "verification_rejected", certificate, None
            self.infra_reason = (
                "audit_timeout"
                if isinstance(exc, BridgeTimeout)
                else "audit_indeterminate"
            )
            return "verification_indeterminate", certificate, None
        self.diagnostics.extend(verdict.diagnostics)
        if self.cancelled.is_set():
            self.budgets["cancelled"] = None
            return "audit_cancelled", certificate, verdict
        if verdict.status == "rejected":
            self.audit_rejected = True
            return "verification_rejected", certificate, verdict
        if verdict.status == "indeterminate":
            self.infra_reason = "audit_indeterminate"
            if self.clock() >= self.deadline:
                self.budgets["time"] = None
                self.infra_reason = "audit_timeout"
            return "verification_indeterminate", certificate, verdict
        if verdict.certificate_digest != digest_json(
            certificate.model_dump(mode="json")
        ):
            self.infra_reason = "audit_identity"
            self.diagnostics.append(
                "accepted verdict does not identify the audited certificate"
            )
            return "verification_indeterminate", certificate, verdict
        if self.clock() > self.deadline:
            self.budgets["time"] = None
            return "audit_budget", certificate, verdict
        return "verified", certificate, verdict

    def _successor(
        self, entry: _Entry, candidate: Candidate, result: StepResult
    ) -> tuple[str, _Entry | None]:
        parent = entry.node.observation
        child = result.observation
        if result.status in ("advanced", "closed"):
            assert child is not None
            expected_prefix = digest_json(
                tuple(step.candidate_id for step in (*entry.steps, candidate))
            )
            if (
                child.snapshot.session_id != parent.snapshot.session_id
                or child.snapshot.environment_digest
                != parent.snapshot.environment_digest
                or child.snapshot.prefix_digest != expected_prefix
                or child.snapshot.snapshot_id == parent.snapshot.snapshot_id
            ):
                raise BridgeError("step result has invalid snapshot lineage")
            self._remember(child)
            return result.status, self._new_node(child, entry, candidate)
        if child is not None:
            if child != parent:
                raise BridgeError(
                    "failed action did not preserve the parent observation"
                )
            self._remember(child)
        if result.status == "timeout":
            self.budgets["step_timeout"] = None
        elif result.status == "infrastructure_error":
            self.infra_reason = "step_infrastructure"
        return result.status, None

    def _emit(
        self,
        attempt: Attempt,
        observation: Observation,
        candidate_set: CandidateSet,
        next_encoded: EncodedDecision | None,
        *,
        truncated: bool = False,
    ) -> None:
        encoder = self.encoder
        if not self.training or encoder is None or attempt.encoded is None:
            return
        verified = attempt.outcome == "verified"
        transition = Transition(
            episode_id=self.episode_id,
            branch_id="rollout",
            task_id=self.problem.task_id,
            split="train",
            collection_step=attempt.collection_step,
            observation=self.nodes[attempt.node_id].observation,
            candidate_set=attempt.candidate_set,
            chosen_candidate_id=attempt.candidate.candidate_id,
            reward=self.options.verified_reward
            if verified
            else -self.options.action_cost,
            next_observation=observation,
            next_candidate_set=candidate_set,
            terminated=verified,
            truncated=truncated,
            outcome=attempt.outcome,
            feature_version=encoder.encoder_digest,
        )
        self.samples.append(
            CollectedSample.capture(
                transition,
                attempt.encoded,
                next_encoded,
                encoder=encoder,
                task_sources={self.problem.task_id: self.problem},
            )
        )

    def _finish_pending(self, decision: Decision | None, reason: str | None) -> None:
        pending = self.pending
        if pending is None:
            return
        if decision is None:
            self.diagnostics.append(
                f"untrainable action at collection step {pending.collection_step}: {reason or 'no eligible continuation'}"
            )
        else:
            self._emit(
                pending,
                decision.observation,
                decision.candidate_set,
                decision.encoded,
                truncated=reason is not None,
            )
        self.pending = None

    def _attempt(self, entry: _Entry, decision: Decision, choice: Choice) -> None:
        candidate = next(
            (
                candidate
                for candidate, eligible in zip(
                    decision.candidate_set.candidates,
                    decision.candidate_set.eligible,
                    strict=True,
                )
                if candidate.candidate_id == choice.candidate_id and eligible
            ),
            None,
        )
        if candidate is None:
            raise ValueError(
                "policy chose a candidate outside the current eligibility mask"
            )
        applied = self._apply(entry, candidate)
        if applied is None:
            reason = "cancelled" if self.cancelled.is_set() else "action budget"
            self._finish_pending(decision, reason)
            return
        self._finish_pending(decision, "cancelled" if self.cancelled.is_set() else None)
        result, reused_probe = applied
        entry.attempted.add(candidate.candidate_id)
        self.diagnostics.extend(result.diagnostics)
        try:
            outcome, child = self._successor(entry, candidate, result)
        except BridgeError as exc:
            self.infra_reason = "step_lineage"
            self.diagnostics.append(str(exc))
            outcome, child = "infrastructure_error", None
        certificate = verdict = None
        if outcome == "closed" and child is not None:
            outcome, certificate, verdict = self._audit(child)
        if self.cancelled.is_set():
            self.budgets["cancelled"] = None
            outcome = (
                "audit_cancelled"
                if result.status == "closed" and child is not None
                else "cancelled"
            )
        attempt = Attempt(
            node_id=entry.node.node_id,
            collection_step=decision.collection_step,
            candidate_set=decision.candidate_set,
            candidate=candidate,
            encoded=decision.encoded,
            scores=choice.scores,
            reused_probe=reused_probe,
            result=result,
            outcome=outcome,
            child_id=None if child is None else child.node.node_id,
            certificate=certificate,
            verdict=verdict,
        )
        self.attempts.append(attempt)
        if outcome == "verified" and child is not None:
            self.accepted = attempt
            terminal = CandidateSet(
                state_digest=child.node.observation.state_digest,
                policy_digest=self.eligibility.policy_digest,
                candidates=(),
                eligible=(),
            )
            self._remember(child.node.observation, terminal)
            self._emit(attempt, child.node.observation, terminal, None)
            return
        available = self._available(entry, decision.candidate_set)
        has_alternative = any(available.eligible)
        if outcome == "rejected" and result.observation is not None:
            self._remember(result.observation, available)
        if self.mode != "rollout":
            if has_alternative:
                self._push(entry)
            elif entry.generated is not None and entry.generated.stopped_after_closure:
                # Resume the same parent after all candidates in the early batch
                # have been tried. The original closure never became a proof.
                entry.generated = None
                self._push(entry)
        if outcome == "advanced" and child is not None:
            self._push(child)
            if self.training:
                self.pending = attempt
        elif (
            self.mode == "rollout"
            and outcome == "rejected"
            and result.observation is not None
        ):
            if has_alternative:
                self._push(entry)
            if self.training:
                self.pending = attempt
        elif self.training:
            self.diagnostics.append(
                f"untrainable action at collection step {attempt.collection_step}: {outcome}"
            )

    def run(self) -> None:
        session_id = None
        try:
            if self.cancelled.is_set():
                self.budgets["cancelled"] = None
                return
            remaining = self._remaining_time(continuation=True)
            if remaining <= 0:
                self.budgets["time"] = None
                return
            self._count("opens")
            open_limits = self.limits.model_copy(
                update={"task_timeout_seconds": remaining}
            )
            if isinstance(self.bridge, LeanBridge):
                snapshot, observation = self.bridge.open(
                    self.problem, open_limits, cancelled=self.cancelled
                )
            else:
                snapshot, observation = self.bridge.open(self.problem, open_limits)
            session_id = snapshot.session_id
            if (
                snapshot != observation.snapshot
                or not observation.goals
                or snapshot.prefix_digest != digest_json(())
            ):
                raise BridgeError(
                    "bridge returned an invalid initial proof observation"
                )
            self._remember(observation)
            self._push(self._new_node(observation, None, None))
            while self.frontier and self.accepted is None:
                entry = self._pop()
                cutoff = self._cutoff(entry)
                if cutoff is not None:
                    self.budgets[cutoff] = None
                    if self.pending is not None and cutoff != "cancelled":
                        if entry.generated is None:
                            self._generate(entry, continuation=True)
                        self._finish_pending(self._decision(entry), cutoff)
                    if cutoff == "cancelled":
                        break
                    continue
                if entry.generated is None:
                    self._generate(entry, continuation=False)
                decision = self._decision(entry)
                if self.cancelled.is_set():
                    self.budgets["cancelled"] = None
                    self._finish_pending(decision, "cancelled")
                    break
                if decision is None:
                    self._finish_pending(None, "no eligible continuation")
                    if self._remaining_time() <= 0:
                        self.budgets["time"] = None
                    continue
                self._attempt(entry, decision, self.policy.choose(decision))
        except BridgeTimeout as exc:
            self.budgets["step_timeout"] = None
            self.diagnostics.append(str(exc))
        except BridgeError as exc:
            self.infra_reason = "worker_failure"
            self.diagnostics.append(str(exc))
        finally:
            if self.accepted is None and self.cancelled.is_set():
                self.budgets["cancelled"] = None
            if session_id is not None:
                self.bridge.close(session_id)
            self._finish_pending(None, "no eligible continuation")

    def report(self) -> SearchReport:
        accepted = self.accepted
        status: SearchStatus
        reason: str
        if accepted is not None:
            status, reason = "verified", "audit_accepted"
        elif "cancelled" in self.budgets:
            status, reason = "budget_exhausted", "cancelled"
        elif self.infra_reason is not None:
            status, reason = "infrastructure_error", self.infra_reason
        elif self.budgets:
            status, reason = "budget_exhausted", next(iter(self.budgets))
        elif self.audit_rejected:
            status, reason = "verification_rejected", "audit_rejected"
        else:
            status, reason = "candidate_exhausted", "frontier_exhausted"
        return SearchReport(
            problem=self.problem,
            policy_digest=self.eligibility.policy_digest,
            eligibility_digest=self.eligibility.eligibility_digest,
            policy_name=self.policy.name,
            mode=self.mode,
            episode_id=self.episode_id,
            limits=self.limits,
            options=self.options,
            verification_reserve_seconds=self.verification_reserve,
            continuation_reserve_seconds=self.continuation_reserve,
            status=status,
            reason=reason,
            budget_reasons=tuple(self.budgets),
            work=Work.model_validate(
                {
                    **self.work,
                    "selected_actions": len(self.attempts),
                    "elapsed_seconds": self.clock() - self.started,
                }
            ),
            nodes=tuple(self.nodes.values()),
            generations=tuple(self.generations),
            attempts=tuple(self.attempts),
            last_observation=self.last_observation,
            final_candidate_set=self.final_candidate_set,
            certificate=None if accepted is None else accepted.certificate,
            verdict=None if accepted is None else accepted.verdict,
            transitions=tuple(sample.trace.transition for sample in self.samples),
            samples=tuple(self.samples),
            diagnostics=tuple(self.diagnostics),
        )


def solve(
    problem: Problem,
    eligibility: EligibilityPolicy,
    bridge: Bridge,
    generator: Generator,
    verifier: ProofVerifier,
    limits: Limits,
    *,
    policy: ActionPolicy | None = None,
    mode: SearchMode = "best_first",
    encoder: FeatureEncoder | None = None,
    episode_id: str | None = None,
    collection_step: int = 0,
    options: SearchOptions | None = None,
    clock: Callable[[], float] = time.monotonic,
    cancelled: Event | None = None,
) -> SearchReport:
    """Solve the original statement and audit any apparent closing branch.

    Best-first orders frontier entries by action depth, residual goal count,
    and insertion order. Deterministic mode traverses depth-first with stable
    candidate order. Rollout follows a single behavior branch and records
    eligible train decisions with actual Lean successors.
    """
    if mode not in {"best_first", "deterministic", "rollout"}:
        raise ValueError("unknown search mode")
    if type(collection_step) is not int or collection_step < 0:
        raise ValueError("collection step must be a nonnegative integer")
    eligibility.validate_for(problem, ())
    selected_policy = policy or DeterministicPolicy()
    if encoder is None and (
        selected_policy.requires_encoding
        or (mode == "rollout" and problem.split == "train")
    ):
        encoder = FeatureEncoder()
    run = _Run(
        problem,
        eligibility,
        selected_policy,
        bridge,
        generator,
        verifier,
        limits,
        options or SearchOptions(),
        mode,
        encoder,
        episode_id or uuid4().hex,
        collection_step,
        clock,
        cancelled or Event(),
    )
    run.run()
    return run.report()
