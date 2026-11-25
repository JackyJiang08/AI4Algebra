import json
from dataclasses import dataclass
from typing import Any

import pytest
from numpy.random import default_rng
from pydantic import ValidationError

from ai4algebra.contracts import (
    Candidate,
    CandidateSet,
    Certificate,
    Goal,
    Observation,
    Problem,
    Snapshot,
    SourceRef,
    Transition,
    Verdict,
    digest_json,
)
from ai4algebra.memory import FrozenReplay, FrozenReturnMemory, Replay, ReturnMemory
from ai4algebra.representation import (
    DecisionContext,
    EncoderConfig,
    FeatureEncoder,
    StateFeatures,
)

_PROBLEM = Problem(
    task_id="train-task",
    family_id="family",
    split="train",
    source=SourceRef(
        kind="exercise",
        source_id="example",
        revision="v1",
        location="examples/unit",
        content_digest=digest_json("example"),
        attribution="AI4Algebra",
        license_ref="LICENSE",
    ),
    informal_statement="The proposition True holds.",
    lean_name="training_proposition",
    lean_statement="True",
    imports=("Mathlib",),
    mapping_evidence_id="mapping-v1",
)
_CATALOG = {_PROBLEM.task_id: _PROBLEM}
_POLICY = digest_json("policy")
_ENVIRONMENT = digest_json("environment")
_ENCODER = FeatureEncoder(EncoderConfig(state_buckets=8))
_INTRO = Candidate(operation="intro", goal_id="g0")
_EXACT = Candidate(operation="exact", goal_id="g0", lemma="True.intro")
_ASSUMPTION = Candidate(operation="assumption", goal_id="g0")
_VERDICT = Verdict(
    status="accepted",
    replay_passed=True,
    type_passed=True,
    axioms_passed=True,
    dependencies_passed=True,
    lean_version="lean-pin",
    mathlib_revision="mathlib-pin",
)


def _bound_verdict(certificate: Certificate) -> Verdict:
    return _VERDICT.model_copy(
        update={"certificate_digest": digest_json(certificate.model_dump(mode="json"))}
    )


def _observation(
    snapshot_id: str,
    *,
    closed: bool = False,
    environment: str = _ENVIRONMENT,
    prefix: tuple[Candidate, ...] = (),
) -> Observation:
    return Observation(
        snapshot=Snapshot(
            session_id="fixture-session",
            environment_digest=environment,
            prefix_digest=digest_json(
                tuple(candidate.candidate_id for candidate in prefix)
            ),
            snapshot_id=snapshot_id,
        ),
        goals=()
        if closed
        else (Goal(goal_id="g0", target="True", expression='["const","True",[]]'),),
    )


def _candidates(
    obs: Observation,
    *,
    policy: str = _POLICY,
    eligible: tuple[bool, bool, bool] = (True, True, True),
) -> CandidateSet:
    return CandidateSet(
        state_digest=obs.state_digest,
        policy_digest=policy,
        candidates=(_INTRO, _EXACT, _ASSUMPTION) if obs.goals else (),
        eligible=eligible if obs.goals else (),
    )


def _features(obs: Observation, depth: int = 0) -> StateFeatures:
    return _ENCODER.encode_state(obs, DecisionContext(remaining_depth=depth))


def _transition(
    episode: str,
    step: int,
    reward: float,
    observation: Observation,
    next_observation: Observation,
    *,
    chosen: Candidate = _EXACT,
    candidate_set: CandidateSet | None = None,
    next_candidate_set: CandidateSet | None = None,
    outcome: str = "verified",
) -> Transition:
    return Transition(
        episode_id=episode,
        branch_id=f"{episode}-branch",
        task_id=_PROBLEM.task_id,
        split="train",
        collection_step=step,
        reward=reward,
        observation=observation,
        candidate_set=_candidates(observation)
        if candidate_set is None
        else candidate_set,
        next_observation=next_observation,
        next_candidate_set=(
            _candidates(next_observation)
            if next_candidate_set is None
            else next_candidate_set
        ),
        chosen_candidate_id=chosen.candidate_id,
        terminated=outcome == "verified",
        truncated=outcome == "depth_limit",
        outcome=outcome,
        feature_version=_ENCODER.encoder_digest,
    )


@dataclass(frozen=True)
class _Solved:
    transitions: tuple[Transition, ...]
    features: tuple[StateFeatures, ...]
    certificate: Certificate

    def publish(
        self, memory: ReturnMemory, available_at: int, verdict: Verdict | None = None
    ) -> int:
        return memory.publish(
            self.transitions,
            _bound_verdict(self.certificate) if verdict is None else verdict,
            available_at,
            state_features=self.features,
            certificate=self.certificate,
        )


def _certificate(steps: tuple[Candidate, ...], environment: str) -> Certificate:
    return Certificate(
        task_id=_PROBLEM.task_id,
        source_digest=_PROBLEM.source.content_digest,
        statement_digest=_PROBLEM.statement_digest,
        environment_digest=environment,
        policy_digest=_POLICY,
        imports=_PROBLEM.imports,
        steps=steps,
        proof="by exact True.intro",
    )


def _solved(
    episode: str,
    step: int,
    reward: float,
    *,
    depth: int = 0,
    environment: str = _ENVIRONMENT,
    chosen: Candidate = _EXACT,
) -> _Solved:
    observation = _observation(f"{episode}-root", environment=environment)
    closed = _observation(
        f"{episode}-closed", closed=True, environment=environment, prefix=(chosen,)
    )
    transition = _transition(episode, step, reward, observation, closed, chosen=chosen)
    return _Solved(
        (transition,),
        (_features(observation, depth),),
        _certificate((chosen,), environment),
    )


def _branch() -> _Solved:
    root = _observation("branch-root")
    middle = _observation("branch-middle", prefix=(_INTRO,))
    closed = _observation("branch-closed", closed=True, prefix=(_INTRO, _EXACT))
    return _Solved(
        (
            _transition(
                "branch", 2, -1.0, root, middle, chosen=_INTRO, outcome="advanced"
            ),
            _transition("branch", 5, 8.0, middle, closed),
        ),
        (_features(root), _features(middle)),
        _certificate((_INTRO, _EXACT), _ENVIRONMENT),
    )


def _memory(capacity: int = 32, *, k: int = 1) -> ReturnMemory:
    return ReturnMemory(
        capacity,
        gamma=0.5,
        feature_version=_ENCODER.encoder_digest,
        state_size=_ENCODER.state_size,
        policy_digest=_POLICY,
        task_sources=_CATALOG,
        run_id="test-run",
        k=k,
    )


def _restore(
    data: str, cutoff: int = 12, *, expected_artifact_digest: str | None = None
) -> FrozenReturnMemory:
    return FrozenReturnMemory.from_json(
        data,
        run_id="test-run",
        task_sources=_CATALOG,
        feature_version=_ENCODER.encoder_digest,
        state_size=_ENCODER.state_size,
        policy_digest=_POLICY,
        cutoff=cutoff,
        expected_artifact_digest=expected_artifact_digest,
    )


def _rehash(artifact: dict[str, Any]) -> str:
    artifact["artifact_digest"] = digest_json(
        {key: value for key, value in artifact.items() if key != "artifact_digest"}
    )
    return json.dumps(artifact)


def test_replay_round_trips_truncation_policy_masks_and_source() -> None:
    root = _observation("cutoff-root")
    successor = _observation("cutoff-child", prefix=(_EXACT,))
    transition = _transition(
        "cutoff",
        3,
        -0.1,
        root,
        successor,
        next_candidate_set=_candidates(successor, eligible=(False, True, False)),
        outcome="depth_limit",
    )
    replay = Replay(2, run_id="test-run", task_sources=_CATALOG)
    replay.add(transition)
    snapshot = replay.to_json()
    restored = FrozenReplay.from_json(
        snapshot, run_id="test-run", task_sources=_CATALOG
    )
    assert restored.to_json() == snapshot
    assert restored.sample(1, default_rng(0)) == [transition]
    with pytest.raises(ValueError, match="run ID"):
        FrozenReplay.from_json(snapshot, run_id="another-run", task_sources=_CATALOG)
    alternate_source = _PROBLEM.source.model_copy(
        update={"content_digest": digest_json("different source")}
    )
    alternate_problem = _PROBLEM.model_copy(update={"source": alternate_source})
    with pytest.raises(ValueError, match="provenance"):
        FrozenReplay.from_json(
            snapshot,
            run_id="test-run",
            task_sources={_PROBLEM.task_id: alternate_problem},
        )


def test_replay_validates_entire_batch_before_eviction() -> None:
    replay = Replay(1, run_id="test-run", task_sources=_CATALOG)
    original, first, second = (
        _solved(name, step, 1).transitions[0]
        for step, name in enumerate(("original", "first", "second"))
    )
    replay.add(original)
    snapshot = replay.to_json()
    bad_candidate_set = second.candidate_set.model_copy(update={"eligible": (True,)})
    malformed = second.model_copy(update={"candidate_set": bad_candidate_set})
    # A malformed element would fall out of the staged FIFO if validation were deferred.
    with pytest.raises(ValidationError, match="eligibility counts"):
        replay.extend((first, malformed, second))
    with pytest.raises(ValidationError, match="train split"):
        replay.extend((first, second.model_copy(update={"split": "test"})))
    with pytest.raises(ValueError, match="trusted training catalog"):
        replay.extend((first, second.model_copy(update={"task_id": "unlisted-task"})))
    assert replay.to_json() == snapshot
    replay.extend((first, second))
    assert replay.sample(1, default_rng(0)) == [second]


def test_sampling_is_seeded_without_replacement() -> None:
    replay = Replay(3, run_id="test-run", task_sources=_CATALOG)
    replay.extend(_solved(f"ep-{n}", n, 1).transitions[0] for n in range(5))
    first = replay.sample(3, default_rng(42))
    assert first == replay.sample(3, default_rng(42))
    assert {transition.collection_step for transition in first} == {2, 3, 4}
    assert len(replay) == 3
    for batch in (0, 4, True):
        with pytest.raises(ValueError, match="batch"):
            replay.sample(batch, default_rng(0))


def test_return_uses_branch_discount_and_waits_for_delayed_verification() -> None:
    memory = _memory()
    solved = _branch()
    assert solved.publish(memory, available_at=10) == 2
    state = solved.features[0]
    candidates = solved.transitions[0].candidate_set
    assert memory.query(state, candidates, before_step=5, exclude_episode="other") == {}
    assert (
        memory.query(state, candidates, before_step=10, exclude_episode="other") == {}
    )
    assert memory.query(state, candidates, before_step=11, exclude_episode="other") == {
        _INTRO.candidate_id: 3.0,
        _EXACT.candidate_id: 8.0,
    }
    assert (
        memory.query(state, candidates, before_step=11, exclude_episode="branch") == {}
    )


def test_nearest_neighbors_filter_masks_episodes_clock_and_environment_before_ranking() -> (
    None
):
    memory = _memory(k=2)
    for name, step, reward, depth in (
        ("fifo-first", 1, 1.0, 0),
        ("fifo-second", 2, 3.0, 0),
        ("far", 3, 100, 1),
        ("same-episode", 4, 100, 0),
    ):
        _solved(name, step, reward, depth=depth).publish(memory, 10)
    incompatible = _solved("environment", 6, 200, environment=digest_json("elsewhere"))
    incompatible.publish(memory, 10)
    _solved("ineligible", 7, 300, chosen=_ASSUMPTION).publish(memory, 10)
    _solved("alternate-action", 8, 7, chosen=_INTRO).publish(memory, 10)
    _solved("future", 5, 100.0).publish(memory, 15)
    observation = _observation("query")
    candidates = _candidates(observation, eligible=(True, True, False))
    assert memory.query(
        _features(observation),
        candidates,
        before_step=15,
        exclude_episode="same-episode",
    ) == {_EXACT.candidate_id: 2.0, _INTRO.candidate_id: 7.0}


def test_ineligible_branch_cannot_publish() -> None:
    memory = _memory()
    solved = _branch()
    original = _solved("original", 1, 11.0)
    original.publish(memory, 2)
    before = memory.freeze(20).to_json()
    rejected = _VERDICT.model_copy(
        update={"status": "rejected", "replay_passed": False}
    )
    assert solved.publish(memory, 10, rejected) == 0
    assert (
        memory.publish(
            solved.transitions[:1],
            _VERDICT,
            10,
            state_features=solved.features[:1],
            certificate=solved.certificate,
        )
        == 0
    )
    cutoff = solved.transitions[0].model_copy(
        update={"truncated": True, "outcome": "depth_limit"}
    )
    assert (
        memory.publish(
            (cutoff,),
            _VERDICT,
            10,
            state_features=solved.features[:1],
            certificate=solved.certificate,
        )
        == 0
    )
    with pytest.raises(ValidationError, match="without truncation"):
        memory.publish(
            (solved.transitions[-1].model_copy(update={"truncated": True}),),
            _VERDICT,
            10,
            state_features=solved.features[-1:],
            certificate=solved.certificate,
        )
    assert memory.freeze(20).to_json() == before


def test_rejected_attempts_use_same_state_and_are_omitted_from_certificate() -> None:
    memory = _memory()
    root = _observation("rejected-root")
    closed = _observation("rejected-closed", closed=True, prefix=(_EXACT,))
    revised = _candidates(root, eligible=(False, True, True))
    rejected = _transition(
        "retry",
        0,
        -1.0,
        root,
        root,
        chosen=_INTRO,
        next_candidate_set=revised,
        outcome="rejected",
    )
    final = _transition("retry", 1, 4.0, root, closed, candidate_set=revised)
    solved = _Solved(
        (rejected, final), (_features(root),) * 2, _certificate((_EXACT,), _ENVIRONMENT)
    )
    assert solved.publish(memory, 1) == 2
    assert memory.query(
        _features(root), _candidates(root), before_step=2, exclude_episode="current"
    ) == {
        _INTRO.candidate_id: 1.0,
        _EXACT.candidate_id: 4.0,
    }


def test_publication_validates_feature_and_certificate_binding_before_eviction() -> (
    None
):
    memory = _memory(1)
    _solved("original", 1, 11.0).publish(memory, 2)
    before = memory.freeze(20).to_json()
    solved = _branch()
    bad_feature = solved.features[0].model_copy(
        update={"state_digest": digest_json("other")}
    )
    with pytest.raises(ValidationError, match="feature provenance digest"):
        memory.publish(
            solved.transitions,
            _bound_verdict(solved.certificate),
            10,
            state_features=(bad_feature, solved.features[1]),
            certificate=solved.certificate,
        )
    unrelated = _features(_observation("unrelated", prefix=(_ASSUMPTION,)))
    with pytest.raises(ValidationError, match="features do not match"):
        memory.publish(
            solved.transitions,
            _bound_verdict(solved.certificate),
            10,
            state_features=(unrelated, solved.features[1]),
            certificate=solved.certificate,
        )
    with pytest.raises(ValueError, match="certificate does not identify"):
        memory.publish(
            solved.transitions,
            _VERDICT,
            10,
            state_features=solved.features,
            certificate=solved.certificate.model_copy(update={"steps": (_EXACT,)}),
        )
    with pytest.raises(ValueError, match="precedes branch completion"):
        solved.publish(memory, 4)
    with pytest.raises(ValueError, match="distinct proof branches"):
        _Solved(
            (
                solved.transitions[0],
                solved.transitions[1].model_copy(update={"branch_id": "fork"}),
            ),
            solved.features,
            solved.certificate,
        ).publish(memory, 10)
    with pytest.raises(ValueError, match="continuous ordered proof branch"):
        _Solved(
            (
                solved.transitions[0],
                solved.transitions[1].model_copy(update={"collection_step": 1}),
            ),
            solved.features,
            solved.certificate,
        ).publish(memory, 10)
    forged = _observation("false-terminal", closed=True, prefix=(_INTRO, _ASSUMPTION))
    with pytest.raises(ValueError, match="unexpected proof prefix"):
        _Solved(
            (
                solved.transitions[0],
                solved.transitions[1].model_copy(
                    update={
                        "next_observation": forged,
                        "next_candidate_set": _candidates(forged),
                    }
                ),
            ),
            solved.features,
            solved.certificate,
        ).publish(memory, 10)
    assert memory.freeze(20).to_json() == before
    assert solved.publish(memory, 10) == 2
    assert len(memory) == 1
    assert len(memory.freeze(11)) == 1


def test_query_rejects_stale_encoder_policy_and_unrelated_candidate_sets() -> None:
    memory = _memory()
    root = _observation("query-root")
    state = _features(root)
    forged = state.model_copy(
        update={"environment_digest": digest_json("forged environment")}
    )
    with pytest.raises(ValidationError, match="feature provenance digest"):
        memory.query(forged, _candidates(root), before_step=12, exclude_episode="x")
    with pytest.raises(ValueError, match="incompatible policy"):
        memory.query(
            state,
            _candidates(root, policy=digest_json("stale")),
            before_step=12,
            exclude_episode="x",
        )
    encoder = FeatureEncoder(EncoderConfig(hash_seed=7))
    with pytest.raises(ValueError, match="incompatible encoder"):
        memory.query(
            encoder.encode_state(root, DecisionContext(remaining_depth=0)),
            _candidates(root),
            before_step=12,
            exclude_episode="x",
        )
    with pytest.raises(ValueError, match="do not belong"):
        memory.query(
            state,
            _candidates(_observation("other", prefix=(_INTRO,))),
            before_step=12,
            exclude_episode="x",
        )


def test_restore_rejects_hash_timestamp_mask_split_and_source_mismatches() -> None:
    memory = _memory()
    _branch().publish(memory, 10)
    original = memory.freeze(12).to_json()
    assert _restore(original).to_json() == original
    with pytest.raises(ValueError, match="identity or evaluation cutoff"):
        _restore(original, cutoff=13)
    artifact = json.loads(original)
    artifact["records"][0]["discounted_return"] = 123
    with pytest.raises(ValidationError, match="artifact digest does not match"):
        _restore(json.dumps(artifact))
    artifact = json.loads(original)
    artifact["records"][0]["available_at"] = 12
    with pytest.raises(ValidationError, match="unavailable at the evaluation cutoff"):
        _restore(_rehash(artifact))
    artifact = json.loads(original)
    artifact["records"][0]["transition"]["candidate_set"]["eligible"] = [
        False,
        True,
        True,
    ]
    with pytest.raises(ValidationError, match="chosen candidate is not eligible"):
        _restore(_rehash(artifact))
    artifact = json.loads(original)
    artifact["records"][0]["transition"]["split"] = "test"
    with pytest.raises(ValidationError, match="train split"):
        _restore(_rehash(artifact))
    artifact = json.loads(original)
    artifact["records"][0]["source_digest"] = digest_json("untrusted source")
    with pytest.raises(ValueError, match="provenance"):
        _restore(_rehash(artifact))
    artifact = json.loads(original)
    artifact["records"][0]["state_features"]["semantic_digest"] = digest_json(
        "forged state"
    )
    with pytest.raises(ValidationError, match="feature provenance digest"):
        _restore(_rehash(artifact))


def test_eviction_rejects_retrospective_cutoffs_and_persists_floor() -> None:
    memory = _memory(capacity=1)
    first = _solved("first", 1, 1.0)
    second = _solved("second", 3, 2.0)
    first.publish(memory, 2)
    state = first.features[0]
    candidates = first.transitions[0].candidate_set
    assert memory.query(
        state, candidates, before_step=3, exclude_episode="held-out"
    ) == {_EXACT.candidate_id: 1.0}
    second.publish(memory, 4)
    with pytest.raises(ValueError, match="precedes retained return history"):
        memory.query(state, candidates, before_step=3, exclude_episode="held-out")
    with pytest.raises(ValueError, match="precedes retained return history"):
        memory.freeze(4)
    snapshot = memory.freeze(5)
    restored = _restore(snapshot.to_json(), cutoff=5)
    assert restored.cutoff_floor == 5
    assert restored.query(state, candidates, exclude_episode="held-out") == {
        _EXACT.candidate_id: 2.0
    }
    artifact = json.loads(snapshot.to_json())
    artifact["cutoff"] = 4
    with pytest.raises(ValidationError, match="precedes retained return history"):
        _restore(_rehash(artifact), cutoff=4)


def test_duplicate_publication_preserves_availability_scores_and_fifo() -> None:
    memory = _memory(capacity=2, k=2)
    first = _solved("first", 1, 1.0)
    second = _solved("second", 3, 3.0)
    assert first.publish(memory, 2) == 1
    assert second.publish(memory, 4) == 1
    before = memory.freeze(8).to_json()
    assert first.publish(memory, 7) == 0
    assert memory.freeze(8).to_json() == before
    assert memory.freeze(3).query(
        first.features[0],
        first.transitions[0].candidate_set,
        exclude_episode="held-out",
    ) == {_EXACT.candidate_id: 1.0}
    assert memory.freeze(8).query(
        first.features[0],
        first.transitions[0].candidate_set,
        exclude_episode="held-out",
    ) == {_EXACT.candidate_id: 2.0}
    assert _solved("third", 5, 10.0).publish(memory, 6) == 1
    after_eviction = memory.freeze(8).to_json()
    assert first.publish(memory, 7) == 0
    with pytest.raises(ValueError, match="conflicting publication"):
        _solved("first", 1, 100.0).publish(memory, 7)
    with pytest.raises(ValueError, match="clock must be monotone"):
        _solved("out-of-order", 1, 100.0).publish(memory, 5)
    assert memory.freeze(8).to_json() == after_eviction


def test_accepted_verdict_is_bound_to_full_certificate_identity() -> None:
    memory = _memory()
    solved = _solved("ep", 1, 1.0)
    before = memory.freeze(12).to_json()
    with pytest.raises(ValueError, match="verdict does not identify"):
        solved.publish(memory, 3, _VERDICT)
    unrelated = Certificate.model_validate(
        solved.certificate.model_dump(exclude={"proof_digest"}) | {"proof": "by sorry"}
    )
    with pytest.raises(ValueError, match="verdict does not identify"):
        _Solved(solved.transitions, solved.features, unrelated).publish(
            memory, 3, _bound_verdict(solved.certificate)
        )
    different_provenance = solved.certificate.model_copy(
        update={"steps": (_EXACT.model_copy(update={"provenance": "test-alternate"}),)}
    )
    assert different_provenance.proof_digest == solved.certificate.proof_digest
    with pytest.raises(ValueError, match="verdict does not identify"):
        _Solved(solved.transitions, solved.features, different_provenance).publish(
            memory, 3, _bound_verdict(solved.certificate)
        )
    assert memory.freeze(12).to_json() == before


def test_publication_ledger_checks_record_clock_even_without_terminal() -> None:
    memory = _memory()
    _branch().publish(memory, 10)
    snapshot = memory.freeze(12)
    artifact = json.loads(snapshot.to_json())
    artifact["records"].pop()
    artifact["records"][0]["available_at"] = 11
    with pytest.raises(ValidationError, match="provenance or clock differs"):
        _restore(_rehash(artifact))
    artifact = json.loads(snapshot.to_json())
    artifact["records"][0]["discounted_return"] = 99.0
    modified = _rehash(artifact)
    with pytest.raises(ValueError, match="expected artifact digest"):
        _restore(modified, expected_artifact_digest=snapshot.artifact_digest)
    assert (
        _restore(
            snapshot.to_json(), expected_artifact_digest=snapshot.artifact_digest
        ).artifact_digest
        == snapshot.artifact_digest
    )


def test_evaluation_reads_only_frozen_memory_and_preserves_artifact_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = _memory()
    replay = Replay(2, run_id="test-run", task_sources=_CATALOG)
    past = _solved("past", 1, 4.0)
    past.publish(memory, 8)
    replay.extend(past.transitions)
    _solved("delayed", 2, 100.0).publish(memory, 12)
    returns_bytes = memory.freeze(12).to_json().encode()
    replay_bytes = replay.freeze().to_json().encode()
    returns = _restore(returns_bytes.decode())
    evaluation_replay = FrozenReplay.from_json(
        replay_bytes, run_id="test-run", task_sources=_CATALOG
    )
    assert len(returns) == 1
    assert not hasattr(returns, "publish")
    assert not hasattr(evaluation_replay, "add")
    assert not hasattr(evaluation_replay, "extend")

    def forbid(*args: object, **kwargs: object) -> None:
        raise AssertionError("evaluation attempted to mutate training memory")

    monkeypatch.setattr(memory, "publish", forbid)
    monkeypatch.setattr(replay, "add", forbid)
    monkeypatch.setattr(replay, "extend", forbid)
    observation = _observation("evaluation")
    features = _features(observation)
    candidates = _candidates(observation)
    assert returns.query(features, candidates, exclude_episode="evaluation") == {
        _EXACT.candidate_id: 4.0
    }
    with pytest.raises(ValueError, match="frozen return memory cutoff"):
        returns.query(
            features, candidates, exclude_episode="evaluation", before_step=13
        )
    assert evaluation_replay.sample(1, default_rng(0)) == list(past.transitions)
    assert returns.to_json().encode() == returns_bytes
    assert evaluation_replay.to_json().encode() == replay_bytes
    assert returns.artifact_digest == json.loads(returns_bytes)["artifact_digest"]
    assert (
        evaluation_replay.artifact_digest == json.loads(replay_bytes)["artifact_digest"]
    )
