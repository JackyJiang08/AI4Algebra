import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai4algebra.contracts import (
    Argument,
    Candidate,
    Goal,
    Hypothesis,
    Observation,
    Snapshot,
    digest_json,
)
from ai4algebra.representation import (
    ActionFeatures,
    CandidateContext,
    DecisionContext,
    DeclarationSignature,
    EncoderConfig,
    FeatureEncoder,
    StateFeatures,
    encode_candidate,
    encode_state,
    is_approximate_collision,
)

NAT = ["const", "Nat", []]
TRUE = ["const", "True", []]
CONTEXT = DecisionContext(remaining_depth=4, remaining_steps=19, eligible_count=2)


def _goal(
    *,
    goal_id: str = "g0",
    ids: tuple[str, str] = ("l0", "l1"),
    display_name: str = "x",
    universe: str = "u",
    metavariable: str = "_uniq.42",
    local_dependency: int = 0,
) -> Goal:
    return Goal(
        goal_id=goal_id,
        target=f"the equality for {display_name}",
        expression=json.dumps(
            [
                "app",
                [
                    "app",
                    ["const", "Eq", [["param", universe]]],
                    ["local", local_dependency],
                ],
                ["mvar", metavariable],
            ]
        ),
        hypotheses=(
            Hypothesis(
                local_id=ids[0],
                binder_kind="explicit",
                name=display_name,
                type_text="Nat",
                expression=json.dumps(NAT),
            ),
            Hypothesis(
                local_id=ids[1],
                binder_kind="implicit",
                name=display_name,
                type_text=f"some type involving {display_name}",
                expression=json.dumps(["app", ["const", "Fin", []], ["local", 0]]),
                value=json.dumps(["local", 0]),
            ),
        ),
    )


def _observation(
    *goals: Goal, path: str = "default", environment: str = "lean"
) -> Observation:
    return Observation(
        snapshot=Snapshot(
            session_id=path,
            snapshot_id=path,
            environment_digest=digest_json(environment),
            prefix_digest=digest_json(path),
        ),
        goals=goals,
    )


def test_alpha_renaming_and_transport_metadata_do_not_change_features() -> None:
    original = _observation(_goal())
    renamed = _observation(
        _goal(
            goal_id="g8",
            ids=("x1", "x2"),
            display_name="secret-test-label",
            universe="v",
            metavariable="renamed.1",
        ),
        path="secret-task-id",
    )
    lhs = encode_state(original, CONTEXT)
    rhs = encode_state(renamed, CONTEXT)
    assert lhs.values == rhs.values
    assert lhs.semantic_digest == rhs.semantic_digest
    assert lhs.feature_digest == rhs.feature_digest
    assert lhs.provenance_digest != rhs.provenance_digest
    assert lhs.state_digest == original.state_digest != rhs.state_digest
    assert not is_approximate_collision(lhs, rhs)


def test_state_distinguishes_local_dependency_goal_order_and_depth() -> None:
    goal = _goal()
    dependent = _goal(goal_id="g1", local_dependency=1)
    original = encode_state(_observation(goal), CONTEXT)
    changed_dependency = encode_state(_observation(dependent), CONTEXT)
    extra_goal = encode_state(_observation(goal, dependent), CONTEXT)
    reordered = encode_state(_observation(dependent, goal), CONTEXT)
    reduced_depth = encode_state(_observation(goal), DecisionContext(remaining_depth=0))
    assert (
        len(
            {
                item.semantic_digest
                for item in (
                    original,
                    changed_dependency,
                    extra_goal,
                    reordered,
                    reduced_depth,
                )
            }
        )
        == 5
    )
    assert (
        len(
            {
                item.values
                for item in (
                    original,
                    changed_dependency,
                    extra_goal,
                    reordered,
                    reduced_depth,
                )
            }
        )
        == 5
    )


def test_bound_expression_structure_preserves_local_and_de_bruijn_scopes() -> None:
    quantified = [
        "forall",
        "explicit",
        NAT,
        ["lam", "explicit", NAT, ["app", ["bvar", 1], ["local", 0]]],
    ]
    first = Goal(
        goal_id="g0",
        target="display text",
        expression=json.dumps(quantified),
        hypotheses=_goal().hypotheses,
    )
    different_binder = [
        "forall",
        "explicit",
        NAT,
        ["lam", "explicit", NAT, ["app", ["bvar", 0], ["local", 0]]],
    ]
    second = Goal.model_validate(
        first.model_dump() | {"expression": json.dumps(different_binder)}
    )
    assert (
        encode_state(_observation(first), CONTEXT).semantic_digest
        != encode_state(_observation(second), CONTEXT).semantic_digest
    )


@pytest.mark.parametrize(
    "expression",
    [
        "pretty text",
        '["local",2]',
        '["bvar",0]',
        '["app",["nat",true],["sort",["zero"]]]',
        '["sort",["unknown"]]',
        '["const","Nat",{}]',
        '["forall","unsupported",["const","Nat",[]],["bvar",0]]',
    ],
)
def test_invalid_structural_expressions_raise(expression: str) -> None:
    goal = Goal(
        goal_id="g0",
        target="ignored",
        expression=expression,
        hypotheses=_goal().hypotheses,
    )
    with pytest.raises(ValueError, match="Lean"):
        encode_state(_observation(goal), CONTEXT)


def test_hypothesis_cannot_reference_later_local() -> None:
    goal = _goal()
    bad = Hypothesis.model_validate(
        goal.hypotheses[0].model_dump() | {"expression": '["local",1]'}
    )
    modified = Goal.model_validate(
        goal.model_dump() | {"hypotheses": (bad, goal.hypotheses[1])}
    )
    with pytest.raises(ValueError, match="out-of-scope"):
        encode_state(_observation(modified), CONTEXT)


def test_candidate_features_track_goal_and_local_positions_without_provider_metadata() -> (
    None
):
    goal_a = _goal()
    goal_b = _goal(goal_id="g1", ids=("l0", "l2"))
    observation = _observation(goal_a, goal_b)
    original = Candidate(operation="exact", goal_id="g0", local_id="l0")
    different_local = Candidate(operation="exact", goal_id="g0", local_id="l1")
    different_goal = Candidate(operation="exact", goal_id="g1", local_id="l0")
    provider_version = Candidate(
        operation="exact",
        goal_id="g0",
        local_id="l0",
        provenance="openai",
        generator_version="v99",
    )
    first = encode_candidate(original, observation)
    assert first.values != encode_candidate(different_local, observation).values
    assert first.values != encode_candidate(different_goal, observation).values
    assert first.values == encode_candidate(provider_version, observation).values
    assert first.candidate_id == original.candidate_id != provider_version.candidate_id
    with pytest.raises(ValueError, match="unknown local in the focused goal"):
        encode_candidate(
            Candidate(operation="exact", goal_id="g1", local_id="l1"), observation
        )
    with pytest.raises(ValueError, match="unknown goal"):
        encode_candidate(Candidate(operation="intro", goal_id="g9"), observation)


def test_candidate_signature_argument_kind_direction_and_predecision_side_goals() -> (
    None
):
    observation = _observation(_goal())
    candidate = Candidate(
        operation="apply",
        goal_id="g0",
        lemma="foo.rule",
        arguments=(Argument(kind="local", reference="l0"),),
    )
    lhs_signature = DeclarationSignature(name="foo.rule", expression=json.dumps(NAT))
    rhs_signature = DeclarationSignature(name="foo.rule", expression=json.dumps(TRUE))
    lhs_context = CandidateContext(declarations=(lhs_signature,))
    rhs_context = CandidateContext(declarations=(rhs_signature,))
    side_goal = Goal(goal_id="new_goal", target="True", expression=json.dumps(TRUE))
    assert (
        encode_candidate(candidate, observation).values
        != encode_candidate(candidate, observation, lhs_context).values
    )
    assert (
        encode_candidate(candidate, observation, lhs_context).values
        != encode_candidate(candidate, observation, rhs_context).values
    )
    assert (
        encode_candidate(candidate, observation, lhs_context).values
        != encode_candidate(
            candidate,
            observation,
            CandidateContext(declarations=(lhs_signature,), side_goals=(side_goal,)),
        ).values
    )
    changed_argument = Candidate(
        operation="apply",
        goal_id="g0",
        lemma="foo.rule",
        arguments=(Argument(kind="lemma", reference="foo.l0"),),
    )
    assert (
        encode_candidate(candidate, observation).values
        != encode_candidate(changed_argument, observation).values
    )
    forward = Candidate(operation="rewrite", goal_id="g0", local_id="l0")
    backward = Candidate(
        operation="rewrite", goal_id="g0", local_id="l0", direction="backward"
    )
    assert (
        encode_candidate(forward, observation).values
        != encode_candidate(backward, observation).values
    )
    assert (
        encode_candidate(forward, observation).values
        != encode_candidate(
            Candidate(operation="rewrite", goal_id="g0", local_id="l0", location="l1"),
            observation,
        ).values
    )
    with pytest.raises(ValueError, match="referenced declarations"):
        encode_candidate(forward, observation, lhs_context)


def test_overflow_keeps_authoritative_state_and_reports_approximate_collision() -> None:
    encoder = FeatureEncoder(EncoderConfig(max_tokens=1, state_buckets=1))
    first = _observation(_goal(), _goal(goal_id="g1", local_dependency=1))
    second = _observation(_goal(local_dependency=1), _goal(goal_id="g1"))
    lhs = encoder.encode_state(first, CONTEXT)
    rhs = encoder.encode_state(second, CONTEXT)
    assert lhs.overflow and rhs.overflow
    assert len(first.goals) == len(second.goals) == 2
    assert len(first.goals[0].hypotheses) == 2
    assert lhs.state_digest != rhs.state_digest
    assert lhs.feature_digest == rhs.feature_digest
    assert is_approximate_collision(lhs, rhs)


def test_features_are_finite_frozen_versioned_and_have_stable_widths() -> None:
    config = EncoderConfig(state_buckets=37, action_buckets=19, hash_seed=15)
    encoder = FeatureEncoder(EncoderConfig.from_json(config.to_json()))
    observation = _observation(_goal())
    first = encoder.encode_state(observation, CONTEXT)
    second = encoder.encode_candidate(
        Candidate(operation="reflexivity", goal_id="g0"), observation
    )
    assert len(first.values) == encoder.state_size == 45
    assert len(second.values) == encoder.action_size == 36
    assert all(math.isfinite(value) for value in (*first.values, *second.values))
    assert StateFeatures.from_json(first.to_json()) == first
    assert ActionFeatures.from_json(second.to_json()) == second
    encoder.validate_features(first)
    encoder.validate_features(second)
    with pytest.raises(ValueError, match="encoder identity"):
        FeatureEncoder().validate_features(first)
    with pytest.raises(ValidationError, match="digest"):
        StateFeatures.model_validate(first.model_dump() | {"values": (0.0,)})
    with pytest.raises(ValidationError, match="frozen"):
        setattr(config, "hash_seed", 4)
    with pytest.raises(ValueError, match="vector width"):
        encoder.validate_features(first.model_copy(update={"values": (0.0,)}))
    wrong_observation = Observation.model_validate(
        observation.model_dump(exclude={"state_digest"})
        | {"expression_version": "future"}
    )
    with pytest.raises(ValueError, match="expression version"):
        encoder.encode_state(wrong_observation, CONTEXT)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state_digest", digest_json("another observation")),
        ("environment_digest", digest_json("another environment")),
        ("semantic_digest", digest_json("another semantic input")),
        ("overflow", True),
    ],
)
def test_feature_rows_reject_forged_provenance(field: str, value: object) -> None:
    encoder = FeatureEncoder()
    original = encoder.encode_state(_observation(_goal()), CONTEXT)
    tampered = original.model_copy(update={field: value})
    assert tampered.feature_digest == original.feature_digest
    with pytest.raises(ValidationError, match="feature provenance digest"):
        StateFeatures.from_json(tampered.to_json())
    with pytest.raises(ValidationError, match="feature provenance digest"):
        encoder.validate_features(tampered)
    with pytest.raises(ValidationError, match="feature provenance digest"):
        is_approximate_collision(original, tampered)


def test_candidate_feature_provenance_is_bound_to_candidate_id() -> None:
    encoder = FeatureEncoder()
    original = encoder.encode_candidate(
        Candidate(operation="reflexivity", goal_id="g0"), _observation(_goal())
    )
    tampered = original.model_copy(
        update={"candidate_id": digest_json("another action")}
    )
    with pytest.raises(ValidationError, match="feature provenance digest"):
        ActionFeatures.from_json(tampered.to_json())
    with pytest.raises(ValidationError, match="feature provenance digest"):
        encoder.validate_features(tampered)
    with pytest.raises(ValidationError, match="provenance_digest"):
        ActionFeatures.model_validate(
            original.model_dump(exclude={"provenance_digest"})
        )


def test_environment_and_unknown_terms_have_scoped_provenance() -> None:
    goal = Goal(
        goal_id="g0", target="unknown", expression='["const","unseen.αLemma",[]]'
    )
    previous = encode_state(_observation(goal, environment="e1"), CONTEXT)
    subsequent = encode_state(_observation(goal, environment="e2"), CONTEXT)
    assert previous.values == subsequent.values
    assert previous.environment_digest != subsequent.environment_digest
    assert is_approximate_collision(previous, subsequent)


def test_generalization_is_byte_deterministic_across_processes(tmp_path: Path) -> None:
    observation = _observation(_goal())
    filepath = tmp_path / "observed.json"
    filepath.write_text(observation.to_json(), encoding="utf-8")
    script = (
        "from pathlib import Path;"
        "from sys import argv;"
        "from ai4algebra.contracts import Observation;"
        "from ai4algebra.representation import DecisionContext, encode_state;"
        "obs=Observation.from_json(Path(argv[1]).read_bytes());"
        "print(encode_state(obs, DecisionContext(remaining_depth=4, remaining_steps=19, eligible_count=2)).to_json())"
    )
    expected = encode_state(observation, CONTEXT).to_json().encode()
    for seed in ("13", "47"):
        result = subprocess.run(
            [sys.executable, "-c", script, str(filepath)],
            env={
                key: value
                for key, value in os.environ.items()
                if key != "OPENAI_API_KEY"
            }
            | {"PYTHONHASHSEED": seed},
            check=True,
            capture_output=True,
            timeout=10,
        )
        assert result.stdout.strip() == expected
