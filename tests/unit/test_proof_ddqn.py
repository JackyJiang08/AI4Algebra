import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from ai4algebra.contracts import (
    Candidate,
    CandidateSet,
    Goal,
    Observation,
    Operation,
    Problem,
    Snapshot,
    SourceRef,
    Transition,
    digest_json,
)
from ai4algebra.learning import (
    CandidateDDQN,
    CheckpointMetadata,
    CollectedSample,
    DDQNConfig,
    EncodedDecision,
    LearningSample,
    encode_decision,
)
from ai4algebra.learning._network import FloatArray, ScalarQ
from ai4algebra.memory import ReturnMemory
from ai4algebra.representation import (
    DecisionContext,
    EncoderConfig,
    FeatureEncoder,
    StateFeatures,
)

ENCODER = FeatureEncoder()
POLICY = digest_json("tactic policy")
ENVIRONMENT = digest_json("pinned environment")


def _observation(name: str, *, closed: bool = False) -> Observation:
    return Observation(
        snapshot=Snapshot(
            session_id="episode",
            environment_digest=ENVIRONMENT,
            prefix_digest=digest_json(name),
            snapshot_id=name,
        ),
        goals=()
        if closed
        else (
            Goal(
                goal_id=name,
                target="True",
                expression=json.dumps(["const", "True", []]),
            ),
        ),
    )


def _decision(
    observation: Observation,
    operations: Sequence[Operation],
    mask: tuple[bool, ...],
    depth: int = 0,
) -> EncodedDecision:
    return encode_decision(
        ENCODER,
        observation,
        CandidateSet(
            state_digest=observation.state_digest,
            policy_digest=POLICY,
            candidates=tuple(
                Candidate(operation=operation, goal_id=observation.goals[0].goal_id)
                for operation in operations
            ),
            eligible=mask,
        ),
        DecisionContext(remaining_depth=depth, eligible_count=sum(mask)),
    )


def _sample(
    decision: EncodedDecision,
    successor: EncodedDecision | None,
    *,
    reward: float = 1.0,
    terminated: bool = False,
    truncated: bool = False,
) -> LearningSample:
    return LearningSample(
        decision=decision,
        chosen_candidate_id=decision.eligible_actions[0].candidate_id,
        reward=reward,
        next_decision=successor,
        terminated=terminated,
        truncated=truncated,
        outcome="verified" if terminated else "advanced",
        split="train",
    )


def _fixed_learner(huber_delta: float | None = None) -> CandidateDDQN:
    learner = CandidateDDQN(
        ENCODER,
        POLICY,
        DDQNConfig(
            hidden_size=1,
            hidden_layers=1,
            activation="relu",
            gamma=0.5,
            learning_rate=0.01,
            target_update_interval=2,
            huber_delta=huber_delta,
        ),
    )
    action_start = ENCODER.state_size
    for network in (learner._online, learner._target):
        network.layers[0].weights.fill(0.0)
        network.readout.fill(1.0)
    learner._online.layers[0].weights[action_start : action_start + 3, 0] = (
        1.0,
        3.0,
        100.0,
    )
    learner._target.layers[0].weights[action_start : action_start + 3, 0] = (
        10.0,
        0.0,
        102.0,
    )
    learner._target.layers[0].weights[2, 0] = 4.0  # State feature for remaining depth.
    learner._target.offset = -2.0
    return learner


def test_shared_scores_are_invariant_to_order_and_masked_padding() -> None:
    learner = _fixed_learner()
    observation = _observation("root")
    original = _decision(observation, ("assumption", "reflexivity"), (True, True))
    padded = _decision(
        observation, ("intro", "reflexivity", "assumption"), (False, True, True)
    )
    assumption, reflexivity = original.eligible_actions
    assert (
        learner.scores(original)
        == learner.scores(padded)
        == {
            assumption.candidate_id: 1.0,
            reflexivity.candidate_id: 3.0,
        }
    )
    assert learner.score(original.state, assumption) == 1.0
    assert learner.rank(padded) == (reflexivity.candidate_id, assumption.candidate_id)
    assert EncodedDecision.from_json(padded.to_json()) == padded

    initialized = CandidateDDQN(ENCODER, POLICY)
    single = _decision(observation, ("assumption",), (True,))
    context = DecisionContext(remaining_depth=0)
    narrowed = encode_decision(ENCODER, observation, single.candidate_set, context)
    expanded = encode_decision(ENCODER, observation, padded.candidate_set, context)
    assert (
        initialized.scores(narrowed)[assumption.candidate_id]
        == initialized.scores(expanded)[assumption.candidate_id]
    )
    assert initialized.scores(expanded)[assumption.candidate_id] == initialized.score(
        expanded.state, expanded.eligible_actions[1]
    )

    learner._online.layers[0].weights[ENCODER.state_size + 1, 0] = 1.0
    tied = tuple(sorted((assumption.candidate_id, reflexivity.candidate_id)))
    assert learner.rank(original) == learner.rank(padded) == tied
    assert (
        learner.targets((_sample(original, padded),)).selected_candidate_ids == tied[:1]
    )

    with pytest.raises(ValueError, match="do not belong"):
        EncodedDecision(
            state=original.state,
            context=original.context,
            candidate_set=original.candidate_set,
            actions=(reflexivity, assumption),
        )
    unrelated = _decision(_observation("another"), ("assumption",), (True,))
    with pytest.raises(ValueError, match="do not belong"):
        learner.score(unrelated.state, assumption)


def _truncated_transition(
    observation: Observation,
    final: Observation,
    root: EncodedDecision,
    successor: EncodedDecision,
) -> Transition:
    return Transition(
        episode_id="episode",
        branch_id="linear",
        task_id="exercise",
        split="train",
        collection_step=2,
        observation=observation,
        candidate_set=root.candidate_set,
        chosen_candidate_id=root.eligible_actions[0].candidate_id,
        reward=1.0,
        next_observation=final,
        next_candidate_set=successor.candidate_set,
        terminated=False,
        truncated=True,
        outcome="advanced",
        feature_version=ENCODER.encoder_digest,
    )


def test_double_dqn_uses_stored_legal_successor_for_observed_truncation() -> None:
    learner = _fixed_learner()
    observation, final = _observation("root"), _observation("final")
    root = _decision(observation, ("assumption",), (True,), depth=3)
    successor = _decision(
        final, ("assumption", "reflexivity", "intro"), (True, True, False)
    )
    transition = _truncated_transition(observation, final, root, successor)
    with pytest.raises(ValueError, match="requires stored successor"):
        LearningSample.from_transition(transition, root, None)
    with pytest.raises(ValueError, match="does not match recorded transition"):
        LearningSample.from_transition(transition, root, root)

    sample = LearningSample.from_transition(transition, root, successor)
    sample = LearningSample.from_json(sample.to_json())
    reordered = _decision(
        final, ("intro", "reflexivity", "assumption"), (False, True, True)
    )
    bootstrap = learner.targets((sample, _sample(root, reordered)))
    reflexivity = successor.eligible_actions[1].candidate_id
    # Online values [1, 3] pick reflexivity. Target values [8, -2] give 1 + .5 * -2.
    # Scoring the masked candidate or substituting the parent depth would change 0.
    assert bootstrap.values == (0.0, 0.0)
    assert bootstrap.selected_candidate_ids == (reflexivity, reflexivity)
    assert bootstrap.bootstrapped_truncations == 1


def test_targets_batch_legal_successors_and_evaluate_only_selected_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    learner = _fixed_learner()
    root = _decision(_observation("root"), ("assumption",), (True,))
    final = _observation("final")
    multiple = _decision(
        final, ("assumption", "intro", "reflexivity"), (True, False, True)
    )
    single = _decision(final, ("assumption",), (True,), depth=3)
    stopped = _decision(final, ("intro",), (False,))
    terminal = _sample(root, None, reward=0.75, terminated=True)
    samples = (
        _sample(root, multiple),
        terminal,
        _sample(root, None, truncated=True),
        _sample(root, single, truncated=True),
        _sample(root, stopped, truncated=True),
    )
    online_predict, target_predict = learner._online.predict, learner._target.predict
    calls: list[tuple[str, int]] = []

    def score_online(rows: FloatArray) -> FloatArray:
        calls.append(("online", len(rows)))
        return online_predict(rows)

    def score_target(rows: FloatArray) -> FloatArray:
        calls.append(("target", len(rows)))
        return target_predict(rows)

    monkeypatch.setattr(learner._online, "predict", score_online)
    monkeypatch.setattr(learner._target, "predict", score_target)
    targets = learner.targets(samples)
    assert calls == [("online", 3), ("target", 2)]
    assert targets.values == (0.0, 0.75, None, 6.5, None)
    assert targets.selected_candidate_ids == (
        multiple.eligible_actions[1].candidate_id,
        None,
        None,
        single.eligible_actions[0].candidate_id,
        None,
    )
    assert targets.missing_next_observations == targets.no_eligible_next_actions == 1
    assert targets.bootstrapped_truncations == 1


def test_copied_samples_and_decisions_are_revalidated_before_use() -> None:
    learner = _fixed_learner()
    observation, final = _observation("root"), _observation("final")
    root = _decision(observation, ("assumption",), (True,))
    successor = _decision(
        final, ("assumption", "reflexivity", "intro"), (True, True, False)
    )
    sample = _sample(root, successor)
    held_out = sample.model_copy(update={"split": "test"})
    with pytest.raises(ValueError, match="must originate from the train split"):
        learner.targets((held_out,))
    with pytest.raises(ValueError, match="must originate from the train split"):
        learner.update((sample, held_out))

    hidden_intro = ENCODER.encode_candidate(
        successor.candidate_set.candidates[2], final
    )
    misaligned = successor.model_copy(update={"actions": (None, hidden_intro, None)})
    tampered = sample.model_copy(update={"next_decision": misaligned})
    with pytest.raises(
        ValueError, match="eligible candidate is missing stored features"
    ):
        learner.targets((tampered,))
    with pytest.raises(
        ValueError, match="eligible candidate is missing stored features"
    ):
        learner.update((tampered,))
    with pytest.raises(
        ValueError, match="eligible candidate is missing stored features"
    ):
        learner.scores(misaligned)
    with pytest.raises(
        ValueError, match="eligible candidate is missing stored features"
    ):
        learner.select(misaligned)

    first = successor.eligible_actions[0]
    wrong_identity = successor.model_copy(
        update={"actions": (first, hidden_intro, None)}
    )
    with pytest.raises(ValueError, match="do not belong to candidate and state"):
        learner.behavior_scores(wrong_identity)
    assert learner.update_steps == 0
    assert learner.targets((sample,)).values == (0.0,)


def test_collected_sample_binds_transitions_to_original_feature_contexts() -> None:
    learner = _fixed_learner()
    observation, final = _observation("root"), _observation("final")
    root = _decision(observation, ("assumption",), (True,), depth=3)
    successor = _decision(final, ("assumption", "reflexivity"), (True, True))
    transition = _truncated_transition(observation, final, root, successor)
    problem = Problem(
        task_id=transition.task_id,
        source=SourceRef(
            kind="exercise",
            source_id="unit",
            revision="1",
            location="exercises/unit",
            content_digest=digest_json("unit exercise"),
            attribution="AI4Algebra",
            license_ref="LICENSE",
        ),
        informal_statement="Truth is provable.",
        family_id="elementary",
        split="train",
        imports=(),
        lean_name="truth",
        lean_statement="True",
        mapping_evidence_id="unit",
    )
    catalog = {problem.task_id: problem}
    recorded = CollectedSample.capture(
        transition, root, successor, encoder=ENCODER, task_sources=catalog
    )
    restored = CollectedSample.restore(
        recorded.to_json(),
        task_sources=catalog,
        expected_artifact_digest=recorded.artifact_digest,
    )
    assert restored.sample == recorded.sample
    assert restored.trace.transition == transition
    assert restored.sample.next_decision == successor
    assert learner.targets((restored.sample,)).values == (0.0,)

    changed_context = DecisionContext(remaining_depth=3, eligible_count=2)
    misleading = successor.model_copy(update={"context": changed_context})
    with pytest.raises(
        ValueError, match="features do not match recorded decision context"
    ):
        CollectedSample.capture(
            transition, root, misleading, encoder=ENCODER, task_sources=catalog
        )

    regenerated = encode_decision(
        ENCODER, final, successor.candidate_set, changed_context
    )
    differently_collected = CollectedSample.capture(
        transition, root, regenerated, encoder=ENCODER, task_sources=catalog
    )
    assert learner.targets((differently_collected.sample,)).values == (1.5,)
    with pytest.raises(ValueError, match="differs from the expected artifact digest"):
        CollectedSample.restore(
            differently_collected.to_json(),
            task_sources=catalog,
            expected_artifact_digest=recorded.artifact_digest,
        )

    held_out = problem.model_copy(update={"split": "test"})
    with pytest.raises(ValueError, match="trusted training catalog"):
        CollectedSample.restore(
            recorded.to_json(), task_sources={problem.task_id: held_out}
        )


def test_terminal_reward_and_excluded_continuations_have_separate_accounting() -> None:
    learner = _fixed_learner()
    root = _decision(_observation("root"), ("assumption",), (True,))
    closed = _decision(_observation("closed", closed=True), (), ())
    final = _observation("final")
    no_candidates = encode_decision(
        ENCODER,
        final,
        CandidateSet(
            state_digest=final.state_digest,
            policy_digest=POLICY,
            candidates=(Candidate(operation="intro", goal_id="final"),),
            eligible=(False,),
            generation_status="budget_exhausted",
        ),
        DecisionContext(remaining_depth=0),
    )
    terminal = _sample(root, closed, reward=0.75, terminated=True)
    missing = _sample(root, None, truncated=True)
    stopped = _sample(root, no_candidates, truncated=True)
    with pytest.raises(ValueError, match="without truncation"):
        _sample(root, closed, terminated=True, truncated=True)
    assert learner.targets((terminal, missing, stopped)).values == (0.75, None, None)

    untouched = learner._online.snapshot()
    skipped = learner.update((missing, stopped))
    assert (
        skipped.used_samples
        == skipped.update_steps
        == skipped.bootstrapped_truncations
        == 0
    )
    assert skipped.loss is skipped.target_mean is None
    assert skipped.missing_next_observations == skipped.no_eligible_next_actions == 1
    assert not skipped.target_synced
    assert learner._online.snapshot() == untouched

    mixed = learner.update((terminal, missing, stopped))
    assert mixed.loss == 0.0625
    assert mixed.target_mean == 0.75
    assert mixed.used_samples == mixed.update_steps == 1
    assert mixed.missing_next_observations == mixed.no_eligible_next_actions == 1


def test_selected_pair_gradient_matches_finite_differences_and_target_is_detached() -> (
    None
):
    learner = _fixed_learner()
    decision = _decision(
        _observation("root"), ("assumption", "reflexivity"), (True, True), depth=3
    )
    successor = _decision(_observation("final"), ("reflexivity",), (True,))
    sample = _sample(decision, successor)
    target = learner.targets((sample,)).values[0]
    assert target == 0.0
    network = learner._online
    old_target = learner._target.snapshot()

    def loss() -> float:
        return (learner.score(decision.state, sample.chosen_action) - target) ** 2

    checks = (
        (network.layers[0].weights, (2, 0)),
        (network.layers[0].weights, (ENCODER.state_size, 0)),
        (network.layers[0].weights, (ENCODER.state_size + 1, 0)),
        (network.layers[0].bias, (0,)),
        (network.readout, (0,)),
    )
    step = 1e-6
    estimates = []
    for array, index in checks:
        original = float(array[index])
        array[index] = original + step
        plus = loss()
        array[index] = original - step
        minus = loss()
        array[index] = original
        estimates.append((original, (plus - minus) / (2.0 * step)))
    network.offset = step
    plus = loss()
    network.offset = -step
    minus = loss()
    network.offset = 0.0

    metrics = learner.update((sample,))
    assert metrics.loss == 1.0
    updated = (
        network.layers[0].weights,
        network.layers[0].weights,
        network.layers[0].weights,
        network.layers[0].bias,
        network.readout,
    )
    for (_, updated_index), array, (original, gradient) in zip(
        checks, updated, estimates, strict=True
    ):
        assert (
            original - float(array[updated_index])
        ) / learner.config.learning_rate == pytest.approx(gradient, abs=1e-8)
    assert -network.offset / learner.config.learning_rate == pytest.approx(
        (plus - minus) / (2.0 * step)
    )
    assert network.layers[0].weights[ENCODER.state_size + 1, 0] == 3.0
    assert learner._target.snapshot() == old_target


def test_deep_silu_forward_and_every_parameter_gradient() -> None:
    config = DDQNConfig(hidden_size=2, seed=19)
    assert (config.hidden_layers, config.activation) == (3, "silu")
    network = ScalarQ.initialize(2, config)
    pairs = np.array([[-1.0, 2.0], [0.5, -0.25]])
    targets = np.array([0.2, -0.7])
    expected = pairs
    for layer in network.layers:
        z = expected @ layer.weights + layer.bias
        expected = z / (1.0 + np.exp(-z))
    np.testing.assert_allclose(
        network.predict(pairs), expected @ network.readout + network.offset
    )
    trained = network.copy()
    rate = 0.01
    trained.train(pairs, targets, rate)

    def parameters(net: ScalarQ) -> list[FloatArray]:
        return [
            array for layer in net.layers for array in (layer.weights, layer.bias)
        ] + [net.readout]

    step = 1e-6
    for before, after in zip(parameters(network), parameters(trained), strict=True):
        for index in np.ndindex(before.shape):
            original = before[index]
            before[index] = original + step
            plus = np.mean((network.predict(pairs) - targets) ** 2)
            before[index] = original - step
            minus = np.mean((network.predict(pairs) - targets) ** 2)
            before[index] = original
            assert (original - after[index]) / rate == pytest.approx(
                (plus - minus) / (2 * step), abs=1e-8
            )


def test_hard_target_sync_counts_optimizer_updates_only() -> None:
    learner = CandidateDDQN(ENCODER, POLICY, DDQNConfig(target_update_interval=2))
    decision = _decision(_observation("root"), ("assumption",), (True,))
    batch = (_sample(decision, None, terminated=True),)
    initial = learner._online.snapshot()
    assert learner._target.snapshot() == initial
    assert not np.shares_memory(
        learner._online.layers[0].weights, learner._target.layers[0].weights
    )
    assert not learner.update(batch).target_synced
    skipped = learner.update((_sample(decision, None, truncated=True),))
    assert skipped.update_steps == 1
    assert learner._target.snapshot() == initial != learner._online.snapshot()
    second = learner.update(batch)
    assert second.target_synced and second.update_steps == 2
    assert learner._target.snapshot() == learner._online.snapshot()
    assert not np.shares_memory(
        learner._online.layers[0].weights, learner._target.layers[0].weights
    )


@pytest.mark.parametrize(
    ("reward", "loss", "gradient"),
    [(0.75, 0.03125, 0.25), (101.0, 99.5, -1.0), (-1e155, 1e155, 1.0)],
)
def test_huber_loss_clips_selected_pair_gradients(
    reward: float, loss: float, gradient: float
) -> None:
    learner = _fixed_learner(huber_delta=1.0)
    decision = _decision(_observation("root"), ("assumption",), (True,))
    update = learner.update((_sample(decision, None, reward=reward, terminated=True),))
    assert update.loss == loss
    assert learner._online.offset == -learner.config.learning_rate * gradient


def test_retrieval_blends_concrete_ids_for_behavior_before_epsilon() -> None:
    learner = _fixed_learner()
    original = _decision(
        _observation("root"),
        ("assumption", "reflexivity", "intro"),
        (True, True, False),
    )
    assumption, reflexivity = original.eligible_actions
    masked = original.candidate_set.candidates[2].candidate_id
    rng = np.random.default_rng(7)
    before = rng.bit_generator.state
    calls = 0

    class Memory:
        def query(
            self,
            state: StateFeatures,
            candidates: CandidateSet,
            *,
            before_step: int,
            exclude_episode: str,
        ) -> dict[str, float]:
            nonlocal calls
            calls += 1
            assert state == original.state
            assert candidates.state_digest == state.state_digest
            assert before_step == 4 and exclude_episode == "current"
            assert rng.bit_generator.state == before
            return {assumption.candidate_id: 9.0, masked: 1000.0}

    memory = Memory()
    blended = learner.behavior_scores(
        original,
        memory=memory,
        retrieval_weight=0.5,
        before_step=4,
        exclude_episode="current",
    )
    assert blended == {assumption.candidate_id: 5.0, reflexivity.candidate_id: 3.0}
    assert learner.select(original) == reflexivity.candidate_id
    assert (
        learner.select(
            original,
            memory=memory,
            retrieval_weight=0.5,
            before_step=4,
            exclude_episode="current",
        )
        == assumption.candidate_id
    )

    updated_candidate = Candidate(
        operation="assumption", goal_id="root", generator_version="2"
    )
    observation = _observation("root")
    regenerated = encode_decision(
        ENCODER,
        observation,
        CandidateSet(
            state_digest=observation.state_digest,
            policy_digest=POLICY,
            candidates=(updated_candidate, original.candidate_set.candidates[1]),
            eligible=(True, True),
        ),
        DecisionContext(remaining_depth=0, eligible_count=2),
    )
    assert learner.behavior_scores(
        regenerated,
        memory=memory,
        retrieval_weight=1.0,
        before_step=4,
        exclude_episode="current",
    ) == learner.scores(regenerated)

    expected_rng = np.random.default_rng(7)
    expected_rng.random()
    chosen = sorted(blended)[int(expected_rng.integers(len(blended)))]
    assert (
        learner.select(
            original,
            epsilon=1.0,
            rng=rng,
            memory=memory,
            retrieval_weight=0.5,
            before_step=4,
            exclude_episode="current",
        )
        == chosen
    )
    assert learner.targets((_sample(original, original),)).selected_candidate_ids == (
        reflexivity.candidate_id,
    )
    assert calls == 4


@pytest.mark.parametrize(
    ("huber_delta", "deep"), [(None, False), (1.0, False), (1.0, True)]
)
def test_evaluation_checkpoint_round_trip_and_compatibility(
    tmp_path: Path, huber_delta: float | None, deep: bool
) -> None:
    learner = (
        CandidateDDQN(ENCODER, POLICY, DDQNConfig(huber_delta=huber_delta))
        if deep
        else _fixed_learner(huber_delta)
    )
    decision = _decision(_observation("root"), ("assumption",), (True,))
    successor = _decision(
        _observation("final"), ("assumption", "reflexivity"), (True, True)
    )
    sample = _sample(decision, successor, truncated=True)
    learner.update((sample,))
    memory = ReturnMemory(
        2,
        gamma=learner.config.gamma,
        feature_version=ENCODER.encoder_digest,
        state_size=ENCODER.state_size,
        policy_digest=POLICY,
        task_sources={},
        run_id="training",
    )
    frozen_memory = memory.freeze(4)
    metadata = CheckpointMetadata(
        run_id="training",
        policy_digest=POLICY,
        corpus_digest=digest_json("train corpus"),
        source_digest=digest_json("pinned source"),
        memory_digest=frozen_memory.artifact_digest,
        memory_cutoff=frozen_memory.cutoff,
    )
    checkpoint = tmp_path / "evaluation.json"
    original = learner.save(checkpoint, metadata)
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["artifact_digest"] == original
    assert payload["config"].get("activation", "relu") == learner.config.activation
    assert payload["config"].get("hidden_layers", 1) == learner.config.hidden_layers
    assert payload["config"].get("huber_delta") == huber_delta
    assert ("huber_delta" in payload["config"]) == (huber_delta is not None)
    restored = CandidateDDQN.load(
        checkpoint,
        encoder=ENCODER,
        expected_metadata=metadata,
        expected_artifact_digest=original,
    )
    assert restored.frozen and restored.update_steps == 1
    assert restored.config == learner.config
    assert restored.scores(successor) == learner.scores(successor)
    assert restored.targets((sample,)) == learner.targets((sample,))
    assert restored.scores(successor) == restored.behavior_scores(
        successor,
        memory=frozen_memory,
        retrieval_weight=1.0,
        exclude_episode="evaluation",
    )
    with pytest.raises(TypeError, match="frozen"):
        restored.update((sample,))
    with pytest.raises(ValueError, match="frozen checkpoint snapshot"):
        restored.behavior_scores(
            successor,
            memory=memory.freeze(5),
            retrieval_weight=1.0,
            exclude_episode="evaluation",
        )
    with pytest.raises(ValueError, match="frozen checkpoint snapshot"):
        restored.behavior_scores(
            successor,
            memory=memory,
            retrieval_weight=1.0,
            before_step=4,
            exclude_episode="evaluation",
        )

    copier = tmp_path / "copy.json"
    assert restored.save(copier, metadata) == original
    assert copier.read_bytes() == checkpoint.read_bytes()
    assert set(tmp_path.iterdir()) == {checkpoint, copier}

    with pytest.raises(ValueError, match="differs from the expected artifact digest"):
        CandidateDDQN.load(
            checkpoint,
            encoder=ENCODER,
            expected_metadata=metadata,
            expected_artifact_digest=digest_json("other checkpoint"),
        )

    for changes in (
        {"policy_digest": digest_json("other")},
        {"corpus_digest": digest_json("other")},
        {"source_digest": digest_json("other")},
        {"memory_cutoff": 5},
    ):
        with pytest.raises(ValueError, match="does not match"):
            CandidateDDQN.load(
                checkpoint,
                encoder=ENCODER,
                expected_metadata=metadata.model_copy(update=changes),
            )
    with pytest.raises(ValueError, match="encoder does not match"):
        CandidateDDQN.load(
            checkpoint,
            encoder=FeatureEncoder(EncoderConfig(hash_seed=1)),
            expected_metadata=metadata,
        )
    data = json.loads(checkpoint.read_text(encoding="utf-8"))
    data["update_steps"] = 2
    checkpoint.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="digest does not match"):
        CandidateDDQN.load(checkpoint, encoder=ENCODER, expected_metadata=metadata)

    data["target"]["bias"] = []
    del data["artifact_digest"]
    data["artifact_digest"] = digest_json(data)
    checkpoint.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="network dimensions do not match"):
        CandidateDDQN.load(checkpoint, encoder=ENCODER, expected_metadata=metadata)
