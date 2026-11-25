import json
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from ai4algebra.contracts import (
    Argument,
    Candidate,
    CandidateSet,
    Certificate,
    Goal,
    Hypothesis,
    Observation,
    Problem,
    Record,
    Snapshot,
    SourceRef,
    StepResult,
    Transition,
    Verdict,
    digest_json,
)


def _problem() -> Problem:
    return Problem(
        task_id="idempotent-unit",
        source=SourceRef(
            kind="exercise",
            source_id="unit",
            revision="v1",
            location="group/unit",
            content_digest=digest_json("identity"),
            attribution="AI4Algebra",
            license_ref="LICENSE",
        ),
        informal_statement="Multiplying by one preserves an element.",
        family_id="right-unit",
        split="train",
        imports=("Mathlib.Algebra.Group.Defs",),
        lean_name="times_one",
        lean_statement="a * 1 = a",
        universes=("u",),
        binders=("{G : Type u}", "[Group G]", "(a : G)"),
        mapping_evidence_id="mapping-v1",
    )


def _observation(prefix: str = "root", *, closed: bool = False) -> Observation:
    snapshot = Snapshot(
        session_id="session-1",
        environment_digest=digest_json("lean environment"),
        prefix_digest=digest_json(prefix),
        snapshot_id=prefix,
    )
    return Observation(
        snapshot=snapshot,
        goals=()
        if closed
        else (
            Goal(
                goal_id="g0",
                target="a = a",
                expression="eq fvar0 fvar0",
                hypotheses=(
                    Hypothesis(
                        local_id="h0",
                        binder_kind="explicit",
                        name="a",
                        type_text="Nat",
                        expression="Nat",
                    ),
                ),
            ),
        ),
    )


def _candidates(observation: Observation) -> CandidateSet:
    return CandidateSet(
        state_digest=observation.state_digest,
        policy_digest=digest_json("policy-v1"),
        candidates=(Candidate(operation="reflexivity", goal_id="g0"),)
        if observation.goals
        else (),
        eligible=(True,) if observation.goals else (),
    )


def _verdict() -> Verdict:
    return Verdict(
        status="accepted",
        replay_passed=True,
        type_passed=True,
        axioms_passed=True,
        dependencies_passed=True,
        lean_version="v4.34.0-rc1",
        mathlib_revision="de5ce8a9a66a4aa68a9bdbb35b63a06d34d9ca11",
    )


def _certificate() -> Certificate:
    problem = _problem()
    observation = _observation()
    return Certificate(
        task_id=problem.task_id,
        statement_digest=problem.statement_digest,
        environment_digest=observation.snapshot.environment_digest,
        source_digest=problem.source.content_digest,
        policy_digest=digest_json("policy-v1"),
        imports=problem.imports,
        steps=(Candidate(operation="exact", goal_id="g0", lemma="mul_one"),),
        proof="by exact mul_one a",
    )


def _transition(*, terminal: bool = False) -> Transition:
    observation = _observation()
    candidate_set = _candidates(observation)
    successor = _observation("child", closed=terminal)
    return Transition(
        episode_id="ep1",
        branch_id="branch1",
        task_id=_problem().task_id,
        split="train",
        collection_step=1,
        observation=observation,
        candidate_set=candidate_set,
        chosen_candidate_id=candidate_set.candidates[0].candidate_id,
        reward=1.0 if terminal else -0.01,
        next_observation=successor,
        next_candidate_set=_candidates(successor),
        terminated=terminal,
        truncated=not terminal,
        outcome="verified" if terminal else "depth_limit",
        feature_version="features-v1",
    )


@pytest.mark.parametrize(
    "record",
    [
        _problem(),
        _observation(),
        _candidates(_observation()),
        StepResult(
            status="advanced",
            snapshot=_observation().snapshot,
            observation=_observation(),
        ),
        _certificate(),
        _verdict(),
        _transition(),
        _transition(terminal=True),
    ],
)
def test_wire_round_trip(record: Record) -> None:
    assert type(record).from_json(record.to_json()) == record


def test_problem_is_immutable_and_preserves_statement_context() -> None:
    problem = _problem()
    with pytest.raises(ValidationError, match="frozen"):
        setattr(problem, "lean_statement", "True")
    modified = Problem.model_validate(
        problem.model_dump(exclude={"statement_digest"})
        | {"binders": tuple(reversed(problem.binders))}
    )
    assert modified.statement_digest != problem.statement_digest


@pytest.mark.parametrize(
    ("field", "message"),
    [("schema_version", "schema version"), ("statement_digest", "statement_digest")],
)
def test_reject_missing_wire_identity(field: str, message: str) -> None:
    with pytest.raises(ValidationError, match=f"missing {message}"):
        Problem.from_json(_problem().model_dump_json(exclude={field}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("statement_digest", "a" * 64),
        ("lean_statement", " 	"),
        ("lean_name", "foo\naxiom"),
        ("imports", ["Mathlib", "Mathlib"]),
        ("split", "dev"),
        ("solution", "by sorry"),
    ],
)
def test_reject_invalid_task_documents(field: str, value: object) -> None:
    document = _problem().model_dump(mode="json")
    document[field] = value
    with pytest.raises(ValidationError):
        Problem.from_json(json.dumps(document))


def test_reject_duplicate_wire_fields() -> None:
    serialized = (
        _problem()
        .to_json()
        .replace('"schema_version":1,', '"schema_version":1,"schema_version":1,', 1)
    )
    with pytest.raises(ValueError, match="duplicate JSON field"):
        Problem.from_json(serialized)


def test_reject_wrong_nested_schema_version() -> None:
    document = _problem().model_dump(mode="json")
    document["source"]["schema_version"] = 2
    with pytest.raises(ValidationError, match="unsupported schema version"):
        Problem.from_json(json.dumps(document))


@pytest.mark.parametrize(
    "location",
    [
        "/archive/source.tex",
        r"\archive\source.tex",
        r"C:\archive\source.tex",
        "C:source.tex",
        r"\\server\archive\source.tex",
        "archive/../source.tex",
        r"archive\..\source.tex",
        r"archive\.. \source.tex",
        "archive/source.tex:other",
    ],
)
def test_reject_unsafe_source_locations(location: str) -> None:
    source_fields = _problem().source.model_dump() | {"location": location}
    with pytest.raises(ValidationError, match="relative path without traversal"):
        SourceRef.model_validate(source_fields)


def test_accept_relative_unicode_source_location() -> None:
    location = "archive/β.tex"
    source_fields = _problem().source.model_dump() | {"location": location}
    assert SourceRef.model_validate(source_fields).location == location


def test_ordered_goals_have_distinct_observation_identity() -> None:
    first = _observation()
    second_goal = Goal(goal_id="g1", target="True", expression="true")
    normal = Observation(snapshot=first.snapshot, goals=(*first.goals, second_goal))
    reordered = Observation(snapshot=first.snapshot, goals=(second_goal, *first.goals))
    assert normal.state_digest != reordered.state_digest
    with pytest.raises(ValidationError, match="duplicate goal"):
        Observation(snapshot=first.snapshot, goals=first.goals * 2)
    first_goal = first.goals[0]
    with pytest.raises(ValidationError, match="duplicate local"):
        Goal(
            goal_id=first_goal.goal_id,
            target=first_goal.target,
            expression=first_goal.expression,
            hypotheses=first_goal.hypotheses * 2,
        )


@pytest.mark.parametrize(
    "fields",
    [
        {"operation": "sorry"},
        {"operation": "apply", "lemma": "rfl\nimport Gold"},
        {"operation": "exact", "lemma": "sorry"},
        {"operation": "apply", "lemma": "sorryAx"},
        {"operation": "exact", "lemma": "_root_.sorryAx"},
        {"operation": "simp_only", "simp_lemmas": ("_root_.sorryAx",)},
        {"operation": "apply"},
        {"operation": "exact", "lemma": "rfl", "local_id": "h0"},
        {"operation": "intro", "lemma": "rfl"},
        {"operation": "reflexivity", "direction": "backward"},
        {"operation": "simp_only"},
        {"operation": "simp_only", "simp_lemmas": ("mul_one", "mul_one")},
        {
            "operation": "rewrite",
            "local_id": "h0",
            "arguments": (Argument(kind="local", reference="h1"),),
        },
    ],
)
def test_candidate_rejects_untyped_actions(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Candidate.model_validate({"goal_id": "g0", **fields})


def test_typed_argument_uses_lean_name_validation_for_lemmas() -> None:
    argument = Argument(kind="lemma", reference="foo.β'")
    assert Argument.from_json(argument.to_json()) == argument
    with pytest.raises(ValidationError, match="admission"):
        Argument(kind="lemma", reference="_root_.sorryAx")
    with pytest.raises(ValidationError):
        Argument(kind="local", reference="foo.β'")


def test_candidate_identity_and_reference_validation() -> None:
    observation = _observation()
    candidate = Candidate(
        operation="exact",
        goal_id="g0",
        lemma="foo.β'",
        arguments=(Argument(kind="local", reference="h9"),),
    )
    supplied = candidate.model_dump(exclude={"candidate_id"}) | {"provenance": "openai"}
    assert Candidate.model_validate(supplied).candidate_id == candidate.candidate_id
    with pytest.raises(
        ValidationError, match="candidate and eligibility counts differ"
    ):
        CandidateSet(
            state_digest=observation.state_digest,
            policy_digest=digest_json("policy-v1"),
            candidates=(candidate,),
            eligible=(),
        )
    candidates = CandidateSet(
        state_digest=observation.state_digest,
        policy_digest=digest_json("policy-v1"),
        candidates=(candidate,),
        eligible=(True,),
    )
    with pytest.raises(ValueError, match="unknown local"):
        candidates.validate_for(observation)
    with pytest.raises(ValueError, match="does not belong"):
        candidates.validate_for(_observation("other"))


def test_closure_requires_actual_complete_observation() -> None:
    open_state = _observation()
    closed = _observation("child", closed=True)
    with pytest.raises(ValidationError, match="actual empty observation"):
        StepResult(
            status="closed", observation=open_state, snapshot=open_state.snapshot
        )
    with pytest.raises(ValidationError, match="remaining goal"):
        StepResult(status="advanced", observation=closed, snapshot=closed.snapshot)
    with pytest.raises(ValidationError, match="different snapshot"):
        StepResult(status="closed", observation=closed, snapshot=open_state.snapshot)
    with pytest.raises(ValidationError, match="actual empty observation"):
        StepResult(status="closed")
    assert StepResult(status="closed", observation=closed, snapshot=closed.snapshot)


@pytest.mark.parametrize(
    ("update", "match"),
    [
        (lambda _: {"split": "validation"}, "train split"),
        (lambda _: {"reward": float("nan")}, "finite"),
        (lambda _: {"reward": float("inf")}, "finite"),
        (lambda t: {"chosen_candidate_id": t.observation.state_digest}, "not eligible"),
        (lambda t: {"next_candidate_set": t.candidate_set}, "does not belong"),
        (lambda _: {"terminated": True}, "requires verified closure"),
        (lambda _: {"outcome": "verified"}, "verified outcome requires a terminal"),
        (lambda _: {"outcome": "rejected"}, "requires an unchanged observation"),
        (
            lambda t: {
                "next_candidate_set": t.next_candidate_set.model_copy(
                    update={"eligible": (False,)}
                )
            },
            "eligible continuation",
        ),
    ],
)
def test_reject_invalid_transitions(
    update: Callable[[Transition], dict[str, object]], match: str
) -> None:
    transition = _transition()
    with pytest.raises(ValidationError, match=match):
        Transition.model_validate(transition.model_dump() | update(transition))


def test_rejected_transition_masks_attempted_candidate_on_same_parent() -> None:
    transition = _transition()
    attempted = Candidate(operation="intro", goal_id="g0")
    parent_candidates = CandidateSet.model_validate(
        transition.candidate_set.model_dump()
        | {
            "candidates": (attempted, *transition.candidate_set.candidates),
            "eligible": (True, True),
        }
    )
    fields = transition.model_dump() | {
        "candidate_set": parent_candidates,
        "next_observation": transition.observation,
        "chosen_candidate_id": attempted.candidate_id,
        "outcome": "rejected",
    }
    with pytest.raises(ValidationError, match="must be excluded"):
        Transition.model_validate(fields | {"next_candidate_set": parent_candidates})
    masked = CandidateSet.model_validate(
        parent_candidates.model_dump() | {"eligible": (False, True)}
    )
    assert (
        Transition.model_validate(
            fields | {"next_candidate_set": masked}
        ).next_candidate_set
        == masked
    )


def test_reject_tampered_certificate_and_unchecked_acceptance() -> None:
    document = _certificate().model_dump(mode="json")
    document["proof"] = "by sorry"
    with pytest.raises(ValidationError, match="proof_digest does not match"):
        Certificate.from_json(json.dumps(document))
    verdict = _verdict().model_dump(mode="json")
    verdict["dependencies_passed"] = None
    with pytest.raises(ValidationError, match="every verification check"):
        Verdict.from_json(json.dumps(verdict))
