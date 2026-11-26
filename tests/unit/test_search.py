import json
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Literal

import pytest
from numpy.random import default_rng

from ai4algebra.candidates import CandidateGenerator, CandidateProbe, GenerationResult
from ai4algebra.config import Limits
from ai4algebra.contracts import (
    Candidate,
    CandidateSet,
    Certificate,
    Goal,
    Observation,
    Operation,
    Problem,
    Snapshot,
    SourceRef,
    StepResult,
    Verdict,
    digest_json,
)
from ai4algebra.lean_bridge import BridgeTimeout, LeanBridge
from ai4algebra.lean_bridge.protocol import (
    LEAN_VERSION,
    MATHLIB_REVISION,
    SubprocessWorker,
    WorkerRequest,
    WorkerResult,
)
from ai4algebra.learning import CandidateDDQN, CollectedSample, DDQNConfig
from ai4algebra.memory import ReturnMemory
from ai4algebra.representation import FeatureEncoder
from ai4algebra.search import (
    Choice,
    DDQNPolicy,
    Decision,
    DeterministicPolicy,
    Generator,
    SearchMode,
    SearchOptions,
    solve,
)
from ai4algebra.training._artifacts import RunDirectory
from ai4algebra.verification import EligibilityPolicy, Verifier

_ENV = digest_json("test environment")
_PROBLEM = Problem(
    task_id="tree",
    family_id="tree",
    split="train",
    source=SourceRef(
        kind="fixture",
        source_id="tree",
        revision="1",
        location="tests/unit/test_search.py",
        content_digest=digest_json("fixture"),
        attribution="AI4Algebra",
        license_ref="MIT",
    ),
    informal_statement="Test proof search on a scripted tree",
    imports=(),
    lean_name="tree",
    lean_statement="True",
    mapping_evidence_id="tree",
)
_POLICY = EligibilityPolicy(
    task_id=_PROBLEM.task_id,
    statement_digest=_PROBLEM.statement_digest,
    allowed_imports=(),
)


@dataclass(frozen=True)
class Edge:
    operation: Operation
    goals: tuple[str, ...] = ()
    status: Literal[
        "advanced", "closed", "rejected", "timeout", "infrastructure_error"
    ] = "advanced"
    focus: str = "g0"
    eager: bool = True
    restored: bool = True

    def candidate(self) -> Candidate:
        return Candidate(operation=self.operation, goal_id=self.focus)


Tree = dict[tuple[Operation, ...], tuple[Edge, ...]]


class TreeBridge:
    def __init__(self, tree: Tree) -> None:
        self.tree = tree
        self.states: dict[
            str, tuple[tuple[Operation, ...], tuple[str, ...], Observation]
        ] = {}
        self.stepped: list[tuple[Snapshot, Candidate]] = []
        self.closed: list[str] = []

    def _new_observation(
        self,
        path: tuple[Operation, ...],
        ids: tuple[str, ...],
        goals: tuple[str, ...],
    ) -> Observation:
        prefix = digest_json(ids)
        snapshot = Snapshot(
            snapshot_id=prefix,
            session_id="test-session",
            prefix_digest=prefix,
            environment_digest=_ENV,
        )
        observation = Observation(
            snapshot=snapshot,
            goals=tuple(
                Goal(goal_id=f"g{index}", target=goal, expression='["const","True",[]]')
                for index, goal in enumerate(goals)
            ),
        )
        self.states[snapshot.snapshot_id] = (path, ids, observation)
        return observation

    def open(self, problem: Problem, limits: Limits) -> tuple[Snapshot, Observation]:
        assert problem.statement_digest == _PROBLEM.statement_digest
        assert limits.task_timeout_seconds > 0
        observation = self._new_observation((), (), ("root",))
        return observation.snapshot, observation

    def fork(self, snapshot: Snapshot) -> Snapshot:
        assert self.observe(snapshot).snapshot == snapshot
        return snapshot

    def observe(self, snapshot: Snapshot) -> Observation:
        return self.states[snapshot.snapshot_id][2]

    def step(self, snapshot: Snapshot, candidate: Candidate) -> StepResult:
        self.stepped.append((snapshot, candidate))
        path, ids, parent = self.states[snapshot.snapshot_id]
        edge = next(edge for edge in self.tree[path] if edge.candidate() == candidate)
        observation: Observation | None
        if edge.status in ("advanced", "closed"):
            observation = self._new_observation(
                (*path, edge.operation), (*ids, candidate.candidate_id), edge.goals
            )
        else:
            observation = parent if edge.restored else None
        return StepResult(
            status=edge.status,
            observation=observation,
            snapshot=None if observation is None else observation.snapshot,
        )

    def close(self, session_id: str) -> None:
        self.closed.append(session_id)


class TreeGenerator:
    def __init__(self, bridge: TreeBridge) -> None:
        self.bridge = bridge
        self.calls: list[tuple[tuple[Operation, ...], int, float]] = []

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
        assert probe_limit is not None and timeout_seconds is not None
        path = self.bridge.states[snapshot.snapshot_id][0]
        self.calls.append((path, probe_limit, timeout_seconds))
        probes = []
        calls = 0
        edges = self.bridge.tree.get(path, ())[: limits.max_candidates]
        for edge in edges:
            candidate = edge.candidate()
            if candidate.candidate_id in attempted:
                probe = CandidateProbe(candidate, "already_attempted")
            elif not edge.eager:
                probe = CandidateProbe(candidate, "advanced")
            elif calls >= probe_limit:
                probe = CandidateProbe(candidate, "not_probed")
            else:
                result = self.bridge.step(snapshot, candidate)
                calls += 1
                probe = CandidateProbe(candidate, result.status, result)
            probes.append(probe)
            if stop_on_closure and probe.status == "closed":
                break
        status: Literal["ok", "budget_exhausted", "unavailable"] = "ok"
        if any(probe.status == "infrastructure_error" for probe in probes):
            status = "unavailable"
        elif any(probe.status in ("timeout", "not_probed") for probe in probes):
            status = "budget_exhausted"
        return GenerationResult(
            candidate_set=CandidateSet(
                state_digest=observation.state_digest,
                policy_digest=_POLICY.policy_digest,
                candidates=tuple(probe.candidate for probe in probes),
                eligible=tuple(probe.eligible for probe in probes),
                generation_status=status,
            ),
            probes=tuple(probes),
            candidate_contexts={},
            probe_calls=calls,
            provider_status="not_requested",
            provider_requests=0,
            token_count_requests=0,
            stopped_after_closure=len(probes) < len(edges),
        )


class Audit:
    def __init__(self, deny: frozenset[Operation] = frozenset()) -> None:
        self.deny = deny
        self.calls: list[tuple[Certificate, float]] = []

    def build_certificate(
        self,
        problem: Problem,
        steps: tuple[Candidate, ...],
        eligibility: EligibilityPolicy,
    ) -> Certificate:
        return Certificate(
            task_id=problem.task_id,
            statement_digest=problem.statement_digest,
            environment_digest=_ENV,
            source_digest=problem.source.content_digest,
            policy_digest=eligibility.policy_digest,
            eligibility_digest=eligibility.eligibility_digest,
            imports=problem.imports,
            steps=steps,
            proof="theorem tree : True := True.intro",
        )

    def verify(
        self,
        problem: Problem,
        certificate: Certificate,
        eligibility: EligibilityPolicy,
        *,
        timeout_seconds: float | None = None,
    ) -> Verdict:
        assert timeout_seconds is not None and timeout_seconds > 0.0
        self.calls.append((certificate, timeout_seconds))
        accept = certificate.steps[-1].operation not in self.deny
        return Verdict(
            status="accepted" if accept else "rejected",
            replay_passed=True,
            type_passed=True,
            axioms_passed=True,
            dependencies_passed=accept,
            certificate_digest=digest_json(certificate.model_dump(mode="json")),
            lean_version=LEAN_VERSION,
            mathlib_revision=MATHLIB_REVISION,
        )


@pytest.mark.parametrize("mode", ("deterministic", "best_first"))
def test_retains_productive_parent_and_every_goal(mode: SearchMode) -> None:
    bridge = TreeBridge(
        {
            (): (
                Edge("intro", ("dead branch",)),
                Edge("constructor", ("left", "right")),
            ),
            ("constructor",): (Edge("reflexivity", ("left",), focus="g1"),),
            ("constructor", "reflexivity"): (Edge("assumption", status="closed"),),
        }
    )
    generator = TreeGenerator(bridge)
    audit = Audit()
    report = solve(
        _PROBLEM, _POLICY, bridge, generator, audit, Limits(max_steps=4), mode=mode
    )
    assert report.status == "verified"
    assert report.certificate is not None
    assert tuple(step.operation for step in report.certificate.steps) == (
        "constructor",
        "reflexivity",
        "assumption",
    )
    assert tuple(attempt.node_id for attempt in report.attempts[:2]) == ("n0", "n0")
    assert report.nodes[2].parent_id == "n0"
    assert tuple(goal.target for goal in report.nodes[2].observation.goals) == (
        "left",
        "right",
    )
    assert report.nodes[3].observation.goals[0].target == "left"
    assert (
        report.nodes[3].incoming_candidate
        == Edge("reflexivity", focus="g1").candidate()
    )
    assert report.work.step_calls == len(bridge.stepped) == 4
    assert report.work.reused_probes == 4
    assert report.work.verifier_calls == len(audit.calls) == 1
    assert report.transitions == () and report.samples == ()
    assert bridge.closed == ["test-session"]


def test_best_first_orders_by_depth_residual_goals_and_insertion() -> None:
    bridge = TreeBridge(
        {
            (): (
                Edge("intro", ("left", "right")),
                Edge("constructor", ("first single goal",)),
                Edge("reflexivity", ("second single goal",)),
            ),
            ("intro",): (Edge("assumption", status="closed"),),
            ("constructor",): (Edge("assumption", status="closed"),),
            ("reflexivity",): (Edge("assumption", status="closed"),),
        }
    )
    report = solve(_PROBLEM, _POLICY, bridge, TreeGenerator(bridge), Audit(), Limits())
    assert report.status == "verified" and report.certificate is not None
    assert tuple(attempt.node_id for attempt in report.attempts) == (
        "n0",
        "n0",
        "n0",
        "n2",
    )
    assert report.certificate.steps[0].operation == "constructor"


@pytest.mark.parametrize("mode", ("best_first", "rollout"))
def test_stuck_artifact_preserves_cutoff_goals_and_attempts(
    tmp_path: Path, mode: SearchMode
) -> None:
    bridge = TreeBridge(
        {
            (): (
                Edge("intro", ("left", "right")),
                Edge("constructor", ("alternate",)),
                Edge("reflexivity", status="rejected"),
                Edge("decide", ("not probed",)),
            ),
        }
    )
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        TreeGenerator(bridge),
        Audit(),
        Limits(max_depth=1),
        mode=mode,
        options=SearchOptions(probes_per_node=3),
    )
    directory = RunDirectory(tmp_path)
    files = directory.archive_search("result", report)
    assert files.stuck is not None and files.stuck.path == "result/stuck.json"
    assert files.proof is None
    payload = directory.read(files.stuck)
    assert b'\n  "status": "budget_exhausted"' in payload
    stuck = json.loads(payload)

    assert stuck["reason"] == "probe_limit"
    assert set(stuck["budget"]["reasons"]) == {"depth", "probe_limit"}
    assert stuck["budget"]["step_calls"] == 3
    assert stuck["budget"]["limits"]["max_depth"] == 1
    assert stuck["frontier"] == []
    branches = stuck["cutoffs"]
    assert [branch["reason"] for branch in branches] == ["depth"] * len(branches)
    paths = [
        [tactic["operation"] for tactic in branch["state"]["path_tactics"]]
        for branch in branches
    ]
    assert paths == (
        [["constructor"], ["intro"]] if mode == "best_first" else [["intro"]]
    )
    last = stuck["last_visited"]
    assert last == branches[-1]["state"]
    assert [goal["target"] for goal in last["unresolved_goals"]] == ["left", "right"]
    probes = stuck["attempted_candidates"]["applicability_probes"]
    assert [
        (probe["candidate"]["operation"], probe["outcome"]) for probe in probes
    ] == [
        ("intro", "advanced"),
        ("constructor", "advanced"),
        ("reflexivity", "rejected"),
    ]
    assert len(stuck["attempted_candidates"]["selected_actions"]) == (
        2 if mode == "best_first" else 1
    )


def test_stuck_artifact_retains_frontier_on_cancellation(tmp_path: Path) -> None:
    cancelled = Event()

    class CancellingPolicy(DeterministicPolicy):
        def choose(self, decision: Decision) -> Choice:
            if decision.collection_step == 2:
                cancelled.set()
            return super().choose(decision)

    bridge = TreeBridge(
        {
            (): (
                Edge("intro", ("cut off",)),
                Edge("constructor", ("queued",)),
                Edge("reflexivity", ("other",)),
            )
        }
    )
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        TreeGenerator(bridge),
        Audit(),
        Limits(),
        policy=CancellingPolicy(),
        cancelled=cancelled,
    )
    directory = RunDirectory(tmp_path)
    files = directory.archive_search("result", report)
    assert files.stuck is not None
    stuck = json.loads(directory.read(files.stuck))
    assert stuck["reason"] == "cancelled"
    assert stuck["last_visited"]["node_id"] == "n1"
    (queued,) = stuck["frontier"]
    assert queued["node_id"] == "n2"
    assert queued["unresolved_goals"][0]["target"] == "queued"
    assert queued["path_tactics"][0]["operation"] == "constructor"


def test_stuck_artifact_keeps_open_state_when_audit_rejects_closure(
    tmp_path: Path,
) -> None:
    bridge = TreeBridge({(): (Edge("constructor", status="closed"),)})
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        TreeGenerator(bridge),
        Audit(deny=frozenset({"constructor"})),
        Limits(),
    )
    directory = RunDirectory(tmp_path)
    files = directory.archive_search("result", report)
    assert files.stuck is not None
    stuck = json.loads(directory.read(files.stuck))
    assert stuck["reason"] == "audit_rejected"
    assert stuck["last_observation"]["unresolved_goals"] == []
    assert stuck["last_visited"]["unresolved_goals"][0]["target"] == "root"
    (action,) = stuck["attempted_candidates"]["selected_actions"]
    assert action["step_status"] == "closed"
    assert action["outcome"] == "verification_rejected"


def test_stuck_artifact_preserves_missing_observation(tmp_path: Path) -> None:
    cancelled = Event()
    cancelled.set()
    bridge = TreeBridge({})
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        TreeGenerator(bridge),
        Audit(),
        Limits(),
        cancelled=cancelled,
    )
    directory = RunDirectory(tmp_path)
    files = directory.archive_search("result", report)
    assert files.stuck is not None
    stuck = json.loads(directory.read(files.stuck))
    assert stuck["last_observation"] is None and stuck["last_visited"] is None
    assert stuck["frontier"] == [] and stuck["cutoffs"] == []
    assert stuck["attempted_candidates"] == {
        "selected_actions": [],
        "applicability_probes": [],
    }


def test_rollout_masks_rejection_and_publishes_only_the_chronological_verified_branch() -> (
    None
):
    bridge = TreeBridge(
        {
            (): (
                Edge("intro", status="rejected", eager=False),
                Edge("constructor", ("subgoal",)),
            ),
            ("constructor",): (Edge("assumption", status="closed"),),
        }
    )
    encoder = FeatureEncoder()
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        TreeGenerator(bridge),
        Audit(),
        Limits(max_steps=4),
        mode="rollout",
        encoder=encoder,
        episode_id="episode",
        collection_step=15,
    )
    assert report.status == "verified"
    assert report.certificate is not None and report.verdict is not None
    assert report.work.probe_calls == 2 and report.work.action_calls == 1
    assert report.work.reused_probes == 2
    rejected, progress, terminal = report.transitions
    assert (rejected.outcome, progress.outcome, terminal.outcome) == (
        "rejected",
        "advanced",
        "verified",
    )
    assert tuple(step.collection_step for step in report.transitions) == (15, 16, 17)
    assert rejected.observation == rejected.next_observation
    assert rejected.next_candidate_set.eligible == (False, True)
    assert rejected.next_candidate_set == progress.candidate_set
    assert progress.next_observation == terminal.observation
    assert terminal.terminated and not terminal.truncated and terminal.reward == 1.0
    assert (
        not terminal.next_observation.goals
        and terminal.next_candidate_set.candidates == ()
    )
    assert report.samples[1].sample.decision == report.samples[0].sample.next_decision
    assert report.samples[1].sample.next_decision == report.samples[2].sample.decision
    assert (
        CollectedSample.restore(
            report.samples[0].to_json(),
            task_sources={_PROBLEM.task_id: _PROBLEM},
        )
        == report.samples[0]
    )
    memory = ReturnMemory(
        4,
        gamma=0.5,
        feature_version=encoder.encoder_digest,
        state_size=encoder.state_size,
        policy_digest=_POLICY.policy_digest,
        task_sources={_PROBLEM.task_id: _PROBLEM},
        run_id="unit",
    )
    assert (
        memory.publish(
            report.transitions,
            report.verdict,
            17,
            certificate=report.certificate,
            state_features=tuple(
                sample.sample.decision.state for sample in report.samples
            ),
        )
        == 3
    )


def test_audit_rejection_is_provisional_and_search_may_try_a_sibling() -> None:
    tree: Tree = {
        (): (Edge("constructor", status="closed"), Edge("reflexivity", status="closed"))
    }
    audit = Audit(deny=frozenset({"constructor"}))
    bridge = TreeBridge(tree)
    report = solve(_PROBLEM, _POLICY, bridge, TreeGenerator(bridge), audit, Limits())
    assert report.status == "verified"
    assert tuple(attempt.outcome for attempt in report.attempts) == (
        "verification_rejected",
        "verified",
    )
    assert (
        report.attempts[0].verdict is not None
        and report.attempts[0].verdict.status == "rejected"
    )
    assert len(audit.calls) == 2

    bridge = TreeBridge(tree)
    rollout = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        TreeGenerator(bridge),
        audit,
        Limits(),
        mode="rollout",
    )
    assert rollout.status == "verification_rejected"
    assert rollout.certificate is None and rollout.verdict is None
    assert rollout.samples == () and rollout.transitions == ()
    assert any("untrainable" in diagnostic for diagnostic in rollout.diagnostics)


def test_short_circuit_resumes_same_parent_after_failed_audit() -> None:
    bridge = TreeBridge(
        {(): (Edge("intro", status="closed"), Edge("constructor", status="closed"))}
    )
    generator = TreeGenerator(bridge)
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        generator,
        Audit(deny=frozenset({"intro"})),
        Limits(max_steps=2, max_nodes=1),
        options=SearchOptions(stop_on_closure=True),
    )
    assert report.status == "verified"
    assert tuple(attempt.outcome for attempt in report.attempts) == (
        "verification_rejected",
        "verified",
    )
    assert report.work.nodes_expanded == 1 and report.work.generation_calls == 2
    assert report.work.step_calls == 2
    first, second = report.generations
    assert first.node_id == second.node_id == "n0"
    assert len(first.probes) == 1 and second.probes[0].status == "already_attempted"
    assert first.stopped_after_closure and not second.stopped_after_closure

    bridge = TreeBridge({(): (Edge("intro", status="closed"),)})
    rejected = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        TreeGenerator(bridge),
        Audit(deny=frozenset({"intro"})),
        Limits(max_steps=1),
        options=SearchOptions(stop_on_closure=True),
    )
    assert rejected.status == "verification_rejected"
    assert rejected.budget_reasons == () and rejected.work.generation_calls == 1


@pytest.mark.parametrize(
    ("limit", "options"),
    (
        (Limits(max_depth=1), SearchOptions()),
        (Limits(max_nodes=1), SearchOptions()),
        (Limits(max_steps=2), SearchOptions()),
    ),
)
def test_rollout_cutoff_bootstraps_only_with_a_reserved_actual_continuation(
    limit: Limits,
    options: SearchOptions,
) -> None:
    bridge = TreeBridge(
        {
            (): (Edge("intro", ("next",)),),
            ("intro",): (Edge("assumption", status="closed"),),
        }
    )
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        TreeGenerator(bridge),
        Audit(),
        limit,
        mode="rollout",
        options=options,
    )
    assert report.status == "budget_exhausted"
    assert report.work.nodes_expanded == report.work.continuation_generations == 1
    assert report.work.verifier_calls == 0 and report.work.step_calls == 2
    (transition,) = report.transitions
    assert (
        not transition.terminated
        and transition.truncated
        and transition.reward == -0.01
    )
    assert transition.next_observation == report.last_observation
    assert transition.next_observation.goals[0].target == "next"
    assert report.final_candidate_set == transition.next_candidate_set
    assert transition.next_candidate_set.eligible == (True,)
    assert report.samples[0].sample.next_decision is not None


def test_empty_candidates_and_missing_continuation_create_no_absorbing_sample() -> None:
    bridge = TreeBridge({(): (Edge("intro", ("no generated tactic",)),)})
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        TreeGenerator(bridge),
        Audit(),
        Limits(),
        mode="rollout",
    )
    assert report.status == "candidate_exhausted"
    assert report.last_observation is not None and report.last_observation.goals
    assert (
        report.final_candidate_set is not None
        and report.final_candidate_set.eligible == ()
    )
    assert report.transitions == () and report.samples == ()
    assert any("untrainable" in diagnostic for diagnostic in report.diagnostics)


@pytest.mark.parametrize("restored", (True, False))
def test_step_timeout_never_creates_a_transition(restored: bool) -> None:
    bridge = TreeBridge(
        {(): (Edge("intro", status="timeout", eager=False, restored=restored),)}
    )
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        TreeGenerator(bridge),
        Audit(),
        Limits(),
        mode="rollout",
    )
    assert report.status == "budget_exhausted" and report.reason == "step_timeout"
    assert (report.attempts[0].result.observation is not None) == restored
    assert report.last_observation == report.nodes[0].observation
    assert not report.samples and not report.transitions


def test_exact_ancestor_observation_repeat_retains_distinct_prefix_until_cutoff() -> (
    None
):
    bridge = TreeBridge(
        {
            (): (Edge("intro", ("different",)),),
            ("intro",): (Edge("assumption", ("root",)),),
        }
    )
    report = solve(
        _PROBLEM, _POLICY, bridge, TreeGenerator(bridge), Audit(), Limits(max_depth=2)
    )
    assert report.status == "budget_exhausted" and report.reason == "depth"
    root, child, repeated = report.nodes
    assert (
        repeated.repeated_node_id == root.node_id
        and repeated.parent_id == child.node_id
    )
    assert repeated.observation.goals == root.observation.goals
    assert (
        repeated.observation.snapshot.prefix_digest
        != root.observation.snapshot.prefix_digest
    )


class InvalidPolicy:
    name = "invalid"
    requires_encoding = False

    def choose(self, decision: Decision) -> Choice:
        return Choice(digest_json("outside the mask"))


def test_policies_cannot_step_outside_their_mask() -> None:
    bridge = TreeBridge({(): (Edge("intro", ("next",), eager=False),)})
    with pytest.raises(ValueError, match="outside the current eligibility mask"):
        solve(
            _PROBLEM,
            _POLICY,
            bridge,
            TreeGenerator(bridge),
            Audit(),
            Limits(),
            policy=InvalidPolicy(),
        )
    assert bridge.stepped == []
    assert bridge.closed == ["test-session"]


def test_seeded_ddqn_epsilon_scores_only_eligible_candidates() -> None:
    tree: Tree = {
        (): (
            Edge("intro", status="rejected"),
            Edge("constructor", status="closed"),
            Edge("reflexivity", status="closed"),
        )
    }
    encoder = FeatureEncoder()
    learner = CandidateDDQN(encoder, _POLICY.policy_digest, DDQNConfig(seed=19))

    def choice() -> tuple[str, tuple[str, ...]]:
        bridge = TreeBridge(tree)
        report = solve(
            _PROBLEM,
            _POLICY,
            bridge,
            TreeGenerator(bridge),
            Audit(),
            Limits(),
            mode="rollout",
            policy=DDQNPolicy(learner, epsilon=1.0, rng=default_rng(74)),
            encoder=encoder,
        )
        (attempt,) = report.attempts
        assert report.status == "verified"
        return attempt.candidate.candidate_id, tuple(
            score.candidate_id for score in attempt.scores
        )

    selected, scored = choice()
    assert (selected, scored) == choice()
    assert selected in scored
    assert set(scored) == {edge.candidate().candidate_id for edge in tree[()][1:]}


class WallClock:
    def __init__(self) -> None:
        self.seconds = 0.0

    def __call__(self) -> float:
        return self.seconds


class ChargedGenerator(TreeGenerator):
    def __init__(self, bridge: TreeBridge, extend: Callable[[], None]) -> None:
        super().__init__(bridge)
        self.extend = extend

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
        result = super().generate(
            snapshot,
            observation,
            limits,
            probe_limit=probe_limit,
            timeout_seconds=timeout_seconds,
            attempted=attempted,
            cancelled=cancelled,
            stop_on_closure=stop_on_closure,
        )
        if len(self.calls) == 1:
            self.extend()
        return GenerationResult(
            result.candidate_set,
            result.probes,
            result.candidate_contexts,
            result.probe_calls,
            "ok",
            1,
            1,
        )


def test_wall_budget_counts_generation_and_reserves_verifier_time() -> None:
    clock = WallClock()
    bridge = TreeBridge({(): (Edge("constructor", status="closed"),)})

    def extend() -> None:
        clock.seconds = 7.0

    generator = ChargedGenerator(bridge, extend)
    audit = Audit()
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        generator,
        audit,
        Limits(task_timeout_seconds=10.0, max_steps=1),
        options=SearchOptions(verification_reserve_seconds=3.0),
        clock=clock,
    )
    assert report.status == "verified"
    assert generator.calls == [((), 1, 7.0)]
    assert audit.calls[0][1] == 3.0
    assert report.work.elapsed_seconds == 7.0
    assert report.work.provider_requests == report.work.token_count_requests == 1


def test_wall_budget_preserves_a_reserved_rollout_continuation() -> None:
    clock = WallClock()
    bridge = TreeBridge(
        {
            (): (Edge("intro", ("successor",)),),
            ("intro",): (Edge("constructor", status="closed"),),
        }
    )

    def extend() -> None:
        clock.seconds = 6.0

    generator = ChargedGenerator(bridge, extend)
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        generator,
        Audit(),
        Limits(task_timeout_seconds=10.0),
        options=SearchOptions(
            verification_reserve_seconds=3.0, continuation_reserve_seconds=1.0
        ),
        mode="rollout",
        clock=clock,
    )
    assert report.status == "budget_exhausted" and report.reason == "time"
    assert tuple(call[2] for call in generator.calls) == (6.0, 1.0)
    assert report.transitions[0].truncated
    assert report.transitions[0].next_observation == report.last_observation


class FailingWorker:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def request(
        self, request: WorkerRequest, timeout_seconds: float, cancelled: Event
    ) -> WorkerResult:
        self.operations.append(request.operation)
        if request.operation == "step":
            raise BridgeTimeout("test worker deadline expired")
        return WorkerResult(
            status="observed",
            goals=(
                Goal(goal_id="g0", target="True", expression='["const","True",[]]'),
            ),
        )


class UnprobedGenerator:
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
        candidate = Candidate(operation="constructor", goal_id="g0")
        return GenerationResult(
            candidate_set=CandidateSet(
                state_digest=observation.state_digest,
                policy_digest=_POLICY.policy_digest,
                candidates=(candidate,),
                eligible=(True,),
            ),
            probes=(),
            candidate_contexts={},
            probe_calls=0,
            provider_status="not_requested",
            provider_requests=0,
            token_count_requests=0,
        )


@pytest.mark.parametrize("budget", (1, 2))
@pytest.mark.parametrize("probe", (True, False))
def test_worker_recovery_uses_the_same_budget_as_probes_and_direct_actions(
    budget: int, probe: bool
) -> None:
    worker = FailingWorker()
    bridge = LeanBridge(Path(__file__).resolve().parents[2], worker=worker)
    generator: Generator = (
        CandidateGenerator(_PROBLEM, _POLICY, bridge) if probe else UnprobedGenerator()
    )
    report = solve(
        _PROBLEM, _POLICY, bridge, generator, Audit(), Limits(max_steps=budget)
    )
    assert report.status == "budget_exhausted" and report.reason == "step_timeout"
    assert worker.operations == [
        "observe",
        "step",
        *(["observe"] if budget == 2 else []),
    ]
    assert report.work.step_calls == budget
    assert report.work.recovery_calls == budget - 1
    assert report.work.probe_calls == (budget if probe else 0)
    assert report.work.action_calls == (0 if probe else budget)


class RepeatedGoalWorker:
    def request(
        self, request: WorkerRequest, timeout_seconds: float, cancelled: Event
    ) -> WorkerResult:
        goals = (Goal(goal_id="g0", target="True", expression='["const","True",[]]'),)
        if request.operation == "observe":
            return WorkerResult(status="observed", goals=goals)
        return WorkerResult(status="advanced", goals=goals, parent_goals=goals)


def test_production_generator_retains_equal_goals_with_new_snapshot_lineage() -> None:
    bridge = LeanBridge(
        Path(__file__).resolve().parents[2], worker=RepeatedGoalWorker()
    )
    generator = CandidateGenerator(_PROBLEM, _POLICY, bridge)
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        generator,
        Audit(),
        Limits(max_depth=1, max_candidates=1),
    )
    assert report.status == "budget_exhausted" and report.reason == "depth"
    (generation,) = report.generations
    assert generation.candidate_set.eligible == (True,)
    assert generation.probes[0].status == "advanced"
    parent, child = report.nodes
    assert child.observation.goals == parent.observation.goals
    assert (
        child.observation.snapshot.prefix_digest
        != parent.observation.snapshot.prefix_digest
    )
    assert child.repeated_node_id == parent.node_id
    assert report.attempts[0].outcome == "advanced" and report.work.reused_probes == 1


def test_audit_returning_accepted_after_cancellation_produces_no_terminal_reward() -> (
    None
):
    cancelled = Event()

    class CancellingAudit(Audit):
        def verify(
            self,
            problem: Problem,
            certificate: Certificate,
            eligibility: EligibilityPolicy,
            *,
            timeout_seconds: float | None = None,
        ) -> Verdict:
            accepted = super().verify(
                problem, certificate, eligibility, timeout_seconds=timeout_seconds
            )
            cancelled.set()
            return accepted

    bridge = TreeBridge({(): (Edge("constructor", status="closed"),)})
    report = solve(
        _PROBLEM,
        _POLICY,
        bridge,
        TreeGenerator(bridge),
        CancellingAudit(),
        Limits(),
        mode="rollout",
        cancelled=cancelled,
    )
    assert report.status == "budget_exhausted" and report.reason == "cancelled"
    assert report.work.verifier_calls == 1
    (attempt,) = report.attempts
    assert attempt.outcome == "audit_cancelled"
    assert attempt.verdict is not None and attempt.verdict.status == "accepted"
    assert report.certificate is None and report.verdict is None
    assert report.transitions == () and report.samples == ()


@pytest.mark.parametrize("phase", ("open", "probe", "direct", "audit"))
def test_search_cancels_active_worker_subprocess(tmp_path: Path, phase: str) -> None:
    marker = tmp_path / "worker-started"
    blocking = SubprocessWorker(
        (
            sys.executable,
            "-c",
            "import sys, time; from pathlib import Path; Path(sys.argv[1]).touch(); time.sleep(30)",
            str(marker),
        ),
        tmp_path,
    )
    cancelled = Event()
    goals = (Goal(goal_id="g0", target="True", expression='["const","True",[]]'),)

    class Worker:
        def request(
            self, request: WorkerRequest, timeout_seconds: float, cancelled: Event
        ) -> WorkerResult:
            if (phase == "open" and request.operation == "observe") or (
                phase in {"probe", "direct"} and request.operation == "step"
            ):
                blocking.exchange(b"", timeout_seconds, cancelled)
            if request.operation == "observe":
                return WorkerResult(status="observed", goals=goals)
            return WorkerResult(status="closed", goals=(), parent_goals=goals)

    root = Path(__file__).resolve().parents[2]
    bridge = LeanBridge(root, worker=Worker())
    generator: Generator = (
        UnprobedGenerator()
        if phase == "direct"
        else CandidateGenerator(_PROBLEM, _POLICY, bridge)
    )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            solve,
            _PROBLEM,
            _POLICY,
            bridge,
            generator,
            Verifier(root, transport=blocking),
            Limits(max_candidates=1),
            mode="rollout",
            cancelled=cancelled,
        )
        try:
            deadline = time.monotonic() + 10.0
            while (
                not marker.exists()
                and not future.done()
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            assert marker.exists()
        finally:
            cancelled.set()
        report = future.result(timeout=10.0)
    assert report.status == "budget_exhausted" and report.reason == "cancelled"
    assert report.certificate is None and report.verdict is None
    assert not report.transitions and not report.samples
    assert report.work.recovery_calls == 0
    assert report.work.probe_calls == int(phase in {"probe", "audit"})
    assert report.work.action_calls == int(phase == "direct")
    assert report.work.verifier_calls == int(phase == "audit")
