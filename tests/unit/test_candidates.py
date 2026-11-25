"""Candidate policy, deterministic ordering and disposable applicability probes."""

import json
from dataclasses import dataclass, field
from threading import Event

import pytest

from ai4algebra.candidates import (
    GENERATOR_VERSION,
    CandidateGenerator,
    DeterministicProposer,
    LemmaRule,
    PremiseIndex,
    ProposalRequest,
    ProposalResult,
    instantiate,
)
from ai4algebra.config import Limits
from ai4algebra.contracts import (
    Candidate,
    Goal,
    Hypothesis,
    Observation,
    Problem,
    Snapshot,
    SourceRef,
    StepResult,
    digest_json,
)
from ai4algebra.verification import EligibilityPolicy

_TRUE = '["const","True",[]]'
_ENVIRONMENT = digest_json("fixture environment")
_PARENT = Snapshot(
    session_id="fixture",
    environment_digest=_ENVIRONMENT,
    prefix_digest=digest_json(()),
    snapshot_id="root",
)
_OBSERVATION = Observation(
    snapshot=_PARENT,
    goals=(
        Goal(
            goal_id="g0",
            target="True",
            expression=_TRUE,
            hypotheses=(
                Hypothesis(
                    local_id="l0",
                    name="h",
                    binder_kind="explicit",
                    type_text="True",
                    expression=_TRUE,
                    value='["const","PRIVATE_LOCAL_VALUE",[]]',
                ),
            ),
        ),
    ),
)
_PROBLEM = Problem(
    task_id="task",
    family_id="gold-family-marker",
    split="test",
    informal_statement="A public statement",
    lean_name="Answer.target",
    lean_statement="True",
    mapping_evidence_id="evidence",
    imports=(),
    source=SourceRef(
        kind="fixture",
        source_id="never-send-source-id",
        revision="1",
        location="fixture",
        content_digest=digest_json("source"),
        attribution="A",
        license_ref="MIT",
    ),
)


def _rule(
    name: str, *, module: str = "Init", dependencies: tuple[str, ...] = ()
) -> LemmaRule:
    return LemmaRule(
        name=name,
        statement="True",
        expression=_TRUE,
        module=module,
        dependencies=dependencies,
    )


def _policy(allowed: tuple[str, ...] = ()) -> EligibilityPolicy:
    return EligibilityPolicy(
        task_id=_PROBLEM.task_id,
        statement_digest=_PROBLEM.statement_digest,
        allowed_imports=(),
        allowed_declarations=allowed,
        forbidden_declarations=("Answer.alias",),
        forbidden_imports=("Hidden",),
        bundle_digest=digest_json("global-bundle"),
    )


@dataclass
class FixtureBridge:
    calls: list[tuple[Snapshot, Candidate]] = field(default_factory=list)
    status: str = "closed"

    def open(self, problem: Problem, limits: Limits) -> tuple[Snapshot, Observation]:
        return _PARENT, _OBSERVATION

    def fork(self, snapshot: Snapshot) -> Snapshot:
        assert snapshot == _PARENT
        return snapshot

    def observe(self, snapshot: Snapshot) -> Observation:
        assert snapshot == _PARENT
        return _OBSERVATION

    def close(self, session_id: str) -> None:
        pass

    def step(self, snapshot: Snapshot, candidate: Candidate) -> StepResult:
        self.calls.append((snapshot, candidate))
        if self.status == "timeout":
            return StepResult(status="timeout")
        if self.status == "rejected":
            return StepResult(
                status="rejected", snapshot=snapshot, observation=_OBSERVATION
            )
        child = Snapshot(
            session_id="fixture",
            environment_digest=_ENVIRONMENT,
            prefix_digest=digest_json(candidate.candidate_id),
            snapshot_id=candidate.candidate_id,
        )
        return StepResult(
            status="closed",
            snapshot=child,
            observation=Observation(snapshot=child, goals=()),
        )


@dataclass
class FixtureProposer:
    result: ProposalResult
    requests: list[ProposalRequest] = field(default_factory=list)

    def propose(
        self,
        request: ProposalRequest,
        limits: Limits,
        *,
        timeout_seconds: float | None = None,
        cancelled: Event | None = None,
    ) -> ProposalResult:
        self.requests.append(request)
        return self.result


def test_index_filters_eligibility_before_lookup_and_prompt() -> None:
    permitted = LemmaRule(
        name="Visible.proof",
        statement="True := by exact Answer.alias",
        expression=_TRUE,
        module="Init",
    )
    index = PremiseIndex(
        environment_digest=_ENVIRONMENT,
        imports=(),
        rules=(
            _rule("Hidden.proof", module="Hidden.Solutions"),
            _rule("Answer.alias"),
            _rule("Answer.target"),
            _rule("Public.wrapper", dependencies=("Answer.alias",)),
            LemmaRule(
                name="Public.revealing",
                module="Init",
                statement="Answer.alias",
                expression='["const","Answer.alias",[]]',
            ),
            _rule("External.proof", module="External.Library"),
            permitted,
        ),
    )
    policy = _policy(
        (
            "Answer.target",
            "Visible.proof",
            "Public.wrapper",
            "Public.revealing",
            "Hidden.proof",
            "External.proof",
        )
    )
    assert index.retrieve(_OBSERVATION, policy, 1, problem=_PROBLEM) == (permitted,)
    with pytest.raises(ValueError, match="incompatible"):
        index.model_copy(update={"environment_digest": digest_json("stale")}).retrieve(
            _OBSERVATION, policy, 1
        )
    proposer = FixtureProposer(ProposalResult("unavailable"))
    bridge = FixtureBridge()
    generator = CandidateGenerator(
        _PROBLEM, policy, bridge, premise_index=index, proposer=proposer
    )
    result = generator.generate(_PARENT, _OBSERVATION, Limits(), probe_limit=1)
    assert result.candidate_set.policy_digest == policy.policy_digest
    assert result.provider_status == "unavailable"
    view = proposer.requests[0].prompt_data()
    assert view["premises"] == [
        {"name": "Visible.proof", "type_expression": ["const", "True", []]}
    ]
    for secret in (
        "gold-family-marker",
        "Answer.alias",
        "Hidden.proof",
        "Answer.target",
        "Public.wrapper",
        "Public.revealing",
        "External.proof",
        "never-send-source-id",
        "PRIVATE_LOCAL_VALUE",
    ):
        assert secret not in str(view)
    assert view["statement"] == "True"


def test_malformed_or_forbidden_provider_suggestions_use_typed_fallback() -> None:
    deterministic = CandidateGenerator(_PROBLEM, _policy(), FixtureBridge()).generate(
        _PARENT, _OBSERVATION, Limits(max_candidates=3), probe_limit=3
    )
    for candidate in (
        Candidate(
            operation="exact",
            goal_id="g0",
            lemma="Answer.alias",
            generator_version=GENERATOR_VERSION,
        ),
        Candidate(
            operation="simp_only",
            goal_id="g0",
            simp_lemmas=("Answer.target",),
            generator_version=GENERATOR_VERSION,
        ),
        Candidate(
            operation="intro", goal_id="g0", generator_version=GENERATOR_VERSION
        ).model_copy(update={"operation": "exact?; admit"}),
        Candidate(
            operation="exact",
            goal_id="g0",
            local_id="l99",
            generator_version=GENERATOR_VERSION,
        ),
    ):
        bridge = FixtureBridge()
        generator = CandidateGenerator(
            _PROBLEM,
            _policy(),
            bridge,
            proposer=FixtureProposer(ProposalResult("ok", (candidate,))),
        )
        result = generator.generate(
            _PARENT, _OBSERVATION, Limits(max_candidates=3), probe_limit=3
        )
        assert result.candidate_set.candidates == deterministic.candidate_set.candidates
        assert result.candidate_set.generation_status == "fallback"
        assert result.provider_status == "malformed"
        assert all(attempted != candidate for _, attempted in bridge.calls)


def test_valid_suggestions_are_deduplicated_and_ordered_independently_of_wire_order() -> (
    None
):
    constructor = Candidate(
        operation="constructor",
        goal_id="g0",
        provenance="openai",
        generator_version=GENERATOR_VERSION,
    )
    assumption = Candidate(
        operation="assumption",
        goal_id="g0",
        provenance="openai",
        generator_version=GENERATOR_VERSION,
    )
    results = []
    for options in ((constructor, assumption, constructor), (assumption, constructor)):
        proposer = FixtureProposer(ProposalResult("ok", options))
        generator = CandidateGenerator(
            _PROBLEM, _policy(), FixtureBridge(), proposer=proposer
        )
        result = generator.generate(_PARENT, _OBSERVATION, Limits(max_candidates=4))
        results.append(result.candidate_set)
    assert results[0] == results[1]
    ids = tuple(candidate.candidate_id for candidate in results[0].candidates)
    assert ids[:2] == tuple(sorted((constructor.candidate_id, assumption.candidate_id)))
    assert len(ids) == len(set(ids))


def test_probe_budget_cache_attempt_mask_and_infrastructure_are_distinct() -> None:
    limits = Limits(max_candidates=3)
    bridge = FixtureBridge(status="rejected")
    generator = CandidateGenerator(_PROBLEM, _policy(), bridge)
    first = generator.generate(_PARENT, _OBSERVATION, limits, probe_limit=1)
    assert first.candidate_set.eligible == (False, False, False)
    assert tuple(probe.status for probe in first.probes) == (
        "rejected",
        "not_probed",
        "not_probed",
    )
    assert first.probe_calls == 1 and len(bridge.calls) == 1
    assert first.candidate_set.generation_status == "budget_exhausted"
    reused = generator.generate(_PARENT, _OBSERVATION, limits, probe_limit=0)
    assert reused.probe_calls == 0 and reused.probes[0].reused
    assert reused.probes[0].result == first.probes[0].result
    bridge.status = "timeout"
    attempted = frozenset((first.probes[0].candidate_id,))
    resumed = generator.generate(_PARENT, _OBSERVATION, limits, attempted=attempted)
    assert tuple(probe.status for probe in resumed.probes) == (
        "already_attempted",
        "timeout",
        "not_probed",
    )
    assert resumed.probe_calls == 1 and bridge.observe(_PARENT) == _OBSERVATION


def test_early_closure_keeps_aligned_results_and_saves_other_probes() -> None:
    bridge = FixtureBridge()
    generator = CandidateGenerator(_PROBLEM, _policy(), bridge)
    result = generator.generate(_PARENT, _OBSERVATION, Limits(), stop_on_closure=True)
    (closed,) = result.probes
    assert closed.status == "closed" and result.probe_calls == len(bridge.calls) == 1
    assert result.candidate_set.candidates == (closed.candidate,)
    assert result.candidate_set.eligible == (True,)
    assert result.candidate_set.generation_status == "ok"


def test_rigid_head_fallback_keeps_strong_instantiations_first() -> None:
    def equality(instance: str) -> str:
        coercion = ["app", ["const", "Conversion.coerce", []], ["const", instance, []]]
        return json.dumps(
            [
                "app",
                ["app", ["app", ["const", "Eq", []], ["const", "Nat", []]], coercion],
                ["const", "Nat.zero", []],
            ]
        )

    goal = Goal(
        goal_id="g0", target="coerce x = 0", expression=equality("Conversion.derived")
    )
    inferred = LemmaRule(
        name="Visible.coercion",
        module="Init",
        statement="coerce x = 0",
        expression=equality("Conversion.implicit"),
    )
    exact = LemmaRule(
        name="Visible.exact",
        module="Init",
        statement="coerce x = 0",
        expression=goal.expression,
    )
    candidates = instantiate(inferred, goal)
    assert all(candidate.operation != "exact" for candidate in candidates)
    assert any(candidate.operation == "apply" for candidate in candidates)
    assert any(
        candidate.operation == "rewrite" and candidate.direction == "forward"
        for candidate in candidates
    )

    request = ProposalRequest(
        statement=goal.target, goals=(goal,), premises=(inferred, exact)
    )
    ordered = DeterministicProposer().propose(request, Limits()).candidates
    assert ordered[0].operation == "exact" and ordered[0].lemma == exact.name
    weak_forward = next(
        index
        for index, candidate in enumerate(ordered)
        if candidate.lemma == inferred.name
        and candidate.operation == "rewrite"
        and candidate.direction == "forward"
    )
    assert weak_forward > 0
    strong_reverse = next(
        index
        for index, candidate in enumerate(ordered)
        if candidate.lemma == inferred.name
        and candidate.operation == "rewrite"
        and candidate.direction == "backward"
    )
    assert weak_forward < strong_reverse
    assert all(
        candidate.lemma in (None, inferred.name, exact.name) for candidate in ordered
    )
