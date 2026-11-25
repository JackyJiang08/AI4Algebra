"""Generate typed, policy-checked candidates and probe them on Lean forks."""

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Event
from types import MappingProxyType
from typing import Literal

from ai4algebra.config import Limits
from ai4algebra.contracts import (
    Candidate,
    CandidateSet,
    Goal,
    Observation,
    Problem,
    Snapshot,
    StepResult,
)
from ai4algebra.lean_bridge import Bridge, BridgeError, BridgeTimeout, LeanBridge
from ai4algebra.representation import CandidateContext
from ai4algebra.verification import EligibilityPolicy

from ._proposal import (
    DeterministicProposer,
    ProposalRequest,
    ProposalResult,
    ProviderStatus,
    TacticProposer,
)
from ._rules import (
    GENERATOR_VERSION,
    MAX_OPERANDS,
    LemmaRule,
    PremiseIndex,
    referenced_declarations,
)

ProbeStatus = Literal[
    "advanced",
    "closed",
    "rejected",
    "timeout",
    "infrastructure_error",
    "not_probed",
    "already_attempted",
]


@dataclass(frozen=True)
class CandidateProbe:
    candidate: Candidate
    status: ProbeStatus
    result: StepResult | None = None
    reused: bool = False

    @property
    def candidate_id(self) -> str:
        return self.candidate.candidate_id

    @property
    def eligible(self) -> bool:
        return self.status in ("advanced", "closed")


@dataclass(frozen=True)
class GenerationResult:
    candidate_set: CandidateSet
    probes: tuple[CandidateProbe, ...]
    candidate_contexts: Mapping[str, CandidateContext]
    probe_calls: int
    provider_status: ProviderStatus
    provider_requests: int
    token_count_requests: int
    stopped_after_closure: bool = False
    recovery_calls: int = 0


def _check_candidate(
    candidate: Candidate, observation: Observation, allowed: set[str]
) -> None:
    if referenced_declarations(candidate) - allowed:
        raise ValueError("candidate refers to an inaccessible premise")
    if (
        len(candidate.arguments) > MAX_OPERANDS
        or len(candidate.simp_lemmas) > MAX_OPERANDS
    ):
        raise ValueError("candidate exceeds the typed operand limits")
    goal = next(
        (goal for goal in observation.goals if goal.goal_id == candidate.goal_id), None
    )
    if goal is None:
        raise ValueError("candidate refers to an unknown goal")
    locals_ = {hyp.local_id for hyp in goal.hypotheses}
    if any(
        reference not in locals_
        for reference in (
            *(arg.reference for arg in candidate.arguments if arg.kind == "local"),
            *(
                reference
                for reference in (candidate.local_id, candidate.location)
                if reference is not None
            ),
        )
    ):
        raise ValueError("candidate refers to an unknown local")


class CandidateGenerator:
    """Scope applicability results to a task, frozen policy, and immutable snapshots."""

    def __init__(
        self,
        problem: Problem,
        eligibility: EligibilityPolicy,
        bridge: Bridge,
        *,
        premise_index: PremiseIndex | None = None,
        proposer: TacticProposer | None = None,
    ) -> None:
        self._problem = Problem.from_json(problem.to_json())
        self._policy = EligibilityPolicy.from_json(eligibility.to_json())
        self._policy.validate_for(self._problem, ())
        self._bridge = bridge
        self._index = (
            None
            if premise_index is None
            else PremiseIndex.from_json(premise_index.to_json())
        )
        self._proposer = proposer
        self._deterministic = DeterministicProposer()
        self._probes: dict[tuple[Snapshot, str, str, str], CandidateProbe] = {}

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
    ) -> GenerationResult:
        """Return the candidates, aligned probe results, and charged probe count."""
        observation = Observation.from_json(observation.to_json())
        if snapshot != observation.snapshot:
            raise ValueError("generation snapshot does not match observation")
        limits = Limits.from_json(limits.to_json())
        if probe_limit is not None and (
            type(probe_limit) is not int or probe_limit < 0
        ):
            raise ValueError("probe limit must be a nonnegative integer")
        budget = (
            limits.max_steps
            if probe_limit is None
            else min(probe_limit, limits.max_steps)
        )
        timeout = (
            limits.task_timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("generation timeout must be finite and nonnegative")
        deadline = time.monotonic() + timeout
        rules = (
            ()
            if self._index is None
            else self._index.retrieve(
                observation, self._policy, limits.max_candidates, problem=self._problem
            )
        )
        request = ProposalRequest(
            statement=self._problem.lean_statement,
            binders=self._problem.binders,
            universes=self._problem.universes,
            goals=observation.goals,
            premises=rules,
        )
        deterministic = self._deterministic.propose(request, limits)
        provider = (
            ProposalResult("not_requested")
            if self._proposer is None or not request.goals
            else self._proposer.propose(
                request,
                limits,
                timeout_seconds=max(0.0, deadline - time.monotonic()),
                cancelled=cancelled,
            )
        )
        candidates, provider_status = self._candidates(
            observation, deterministic, provider, rules, limits
        )
        probes, calls, recoveries = self._probe_candidates(
            snapshot,
            observation,
            candidates,
            attempted,
            budget,
            deadline,
            cancelled,
            stop_on_closure,
        )
        status: Literal["ok", "fallback", "budget_exhausted", "unavailable"] = "ok"
        if any(probe.status == "infrastructure_error" for probe in probes):
            status = "unavailable"
        elif any(probe.status in ("not_probed", "timeout") for probe in probes):
            status = "budget_exhausted"
        elif provider_status not in ("ok", "not_requested"):
            status = "fallback"
        signatures = {rule.name: rule.signature for rule in rules}
        contexts = {
            probe.candidate_id: CandidateContext(
                declarations=tuple(
                    signatures[name]
                    for name in sorted(referenced_declarations(probe.candidate))
                ),
                side_goals=self._side_goals(probe, observation),
            )
            for probe in probes
            if probe.eligible
        }
        return GenerationResult(
            candidate_set=CandidateSet(
                state_digest=observation.state_digest,
                policy_digest=self._policy.policy_digest,
                candidates=tuple(probe.candidate for probe in probes),
                eligible=tuple(probe.eligible for probe in probes),
                generation_status=status,
            ),
            probes=probes,
            candidate_contexts=MappingProxyType(contexts),
            probe_calls=calls,
            provider_status=provider_status,
            provider_requests=provider.requests,
            token_count_requests=provider.token_count_requests,
            stopped_after_closure=len(probes) < len(candidates),
            recovery_calls=recoveries,
        )

    def _candidates(
        self,
        observation: Observation,
        deterministic: ProposalResult,
        provider: ProposalResult,
        rules: tuple[LemmaRule, ...],
        limits: Limits,
    ) -> tuple[tuple[Candidate, ...], ProviderStatus]:
        allowed = {rule.name for rule in rules}
        live: list[Candidate] = []
        provider_status = provider.status
        if provider.status == "ok":
            try:
                if len(provider.candidates) > limits.max_candidates:
                    raise ValueError("proposal exceeds the configured candidate limit")
                for candidate in provider.candidates:
                    candidate = Candidate.from_json(candidate.to_json())
                    self._policy.validate_for(self._problem, (candidate,))
                    _check_candidate(candidate, observation, allowed)
                    if candidate.generator_version != GENERATOR_VERSION:
                        raise ValueError("proposal generator version is incompatible")
                    live.append(candidate)
            except ValueError:
                live.clear()
                provider_status = "malformed"
        ordered: dict[str, Candidate] = {}
        for candidate in (
            *sorted(live, key=lambda item: item.candidate_id),
            *deterministic.candidates,
        ):
            self._policy.validate_for(self._problem, (candidate,))
            _check_candidate(candidate, observation, allowed)
            ordered.setdefault(candidate.candidate_id, candidate)
        return tuple(ordered.values())[: limits.max_candidates], provider_status

    def _probe_candidates(
        self,
        snapshot: Snapshot,
        observation: Observation,
        candidates: tuple[Candidate, ...],
        attempted: frozenset[str],
        budget: int,
        deadline: float,
        cancelled: Event | None,
        stop_on_closure: bool,
    ) -> tuple[tuple[CandidateProbe, ...], int, int]:
        probes: list[CandidateProbe] = []
        calls = 0
        recoveries = 0
        interrupted = False
        for candidate in candidates:
            key = (
                snapshot,
                observation.state_digest,
                self._policy.eligibility_digest,
                candidate.candidate_id,
            )
            cached = self._probes.get(key)
            if candidate.candidate_id in attempted:
                probe = CandidateProbe(candidate, "already_attempted")
            elif cached is not None:
                probe = CandidateProbe(
                    candidate, cached.status, cached.result, reused=True
                )
            elif (
                interrupted
                or calls >= budget
                or time.monotonic() >= deadline
                or (cancelled is not None and cancelled.is_set())
            ):
                probe = CandidateProbe(candidate, "not_probed")
            else:
                probe, used, recovered = self._probe(
                    snapshot, candidate, deadline, budget - calls, cancelled
                )
                calls += used
                recoveries += recovered
                interrupted = probe.status in ("timeout", "infrastructure_error")
                if not interrupted:
                    self._probes[key] = probe
            probes.append(probe)
            if stop_on_closure and probe.status == "closed":
                break
        return tuple(probes), calls, recoveries

    def _probe(
        self,
        snapshot: Snapshot,
        candidate: Candidate,
        deadline: float,
        remaining_requests: int,
        cancelled: Event | None,
    ) -> tuple[CandidateProbe, int, int]:
        calls = recoveries = 0
        try:
            branch = self._bridge.fork(snapshot)
            if isinstance(self._bridge, LeanBridge):
                result, usage = self._bridge.step_with_usage(
                    branch,
                    candidate,
                    timeout_seconds=max(0.0, deadline - time.monotonic()),
                    max_worker_requests=remaining_requests,
                    cancelled=cancelled,
                )
                calls, recoveries = usage.worker_requests, usage.recovery_requests
            else:
                calls = 1
                result = self._bridge.step(branch, candidate)
            result = StepResult.from_json(result.to_json())
            status: ProbeStatus = result.status
            if status in ("closed", "advanced") and (
                result.snapshot is None
                or result.snapshot.session_id != snapshot.session_id
                or result.snapshot.environment_digest != snapshot.environment_digest
                or result.snapshot.prefix_digest == snapshot.prefix_digest
            ):
                return (
                    CandidateProbe(candidate, "infrastructure_error"),
                    calls,
                    recoveries,
                )
            return CandidateProbe(candidate, status, result), calls, recoveries
        except BridgeTimeout:
            return CandidateProbe(candidate, "timeout"), calls, recoveries
        except (BridgeError, ValueError):
            return CandidateProbe(candidate, "infrastructure_error"), calls, recoveries

    @staticmethod
    def _side_goals(probe: CandidateProbe, parent: Observation) -> tuple[Goal, ...]:
        if probe.result is None or probe.result.observation is None:
            return ()
        goals = probe.result.observation.goals
        count = len(goals) + 1 - len(parent.goals)
        focus = next(
            index
            for index, goal in enumerate(parent.goals)
            if goal.goal_id == probe.candidate.goal_id
        )
        return goals[focus : focus + max(count, 0)]
