"""Masked Double DQN and a separate epsilon-greedy behavior policy."""

from collections.abc import Sequence
from math import isfinite
from pathlib import Path
from statistics import mean
from threading import RLock
from typing import Protocol

import numpy as np
from numpy.random import Generator
from pydantic import TypeAdapter
from typing_extensions import Self

from ai4algebra.contracts import CandidateSet, Digest
from ai4algebra.representation import ActionFeatures, FeatureEncoder, StateFeatures

from ._checkpoint import EvaluationArtifact
from ._network import FloatArray, ScalarQ
from ._records import (
    CheckpointMetadata,
    DDQNConfig,
    EncodedDecision,
    LearningSample,
    TargetBatch,
    UpdateMetrics,
)

_DIGEST_ADAPTER = TypeAdapter[Digest](Digest)


class ReturnLookup(Protocol):
    def query(
        self,
        state: StateFeatures,
        candidates: CandidateSet,
        *,
        before_step: int,
        exclude_episode: str,
    ) -> dict[str, float]: ...


class CandidateDDQN:
    """Shared scalar Q learner with a read-only evaluation load path."""

    def __init__(
        self,
        encoder: FeatureEncoder,
        policy_digest: str,
        config: DDQNConfig = DDQNConfig(),
    ) -> None:
        self._encoder = encoder
        self._policy_digest = _DIGEST_ADAPTER.validate_python(
            policy_digest, strict=True
        )
        self._config = DDQNConfig.from_json(config.to_json())
        self._online = ScalarQ.initialize(
            encoder.state_size + encoder.action_size,
            self.config.hidden_size,
            self.config.seed,
        )
        self._target = self._online.copy()
        self._update_steps = 0
        self._checkpoint_metadata: CheckpointMetadata | None = None
        self._lock = RLock()

    @property
    def config(self) -> DDQNConfig:
        return self._config

    @property
    def policy_digest(self) -> str:
        return self._policy_digest

    @property
    def update_steps(self) -> int:
        return self._update_steps

    @property
    def frozen(self) -> bool:
        return self._checkpoint_metadata is not None

    def _validate_decision(
        self, decision: EncodedDecision
    ) -> tuple[ActionFeatures, ...]:
        if decision.candidate_set.policy_digest != self.policy_digest:
            raise ValueError("decision candidate policy does not match learner")
        self._encoder.validate_features(decision.state)
        actions = decision.eligible_actions
        for action in actions:
            self._encoder.validate_features(action)
        return actions

    @staticmethod
    def _rows(state: StateFeatures, actions: Sequence[ActionFeatures]) -> FloatArray:
        return np.array(
            [state.values + action.values for action in actions], np.float64
        )

    def score(self, state: StateFeatures, action: ActionFeatures) -> float:
        if (state.state_digest, state.environment_digest) != (
            action.state_digest,
            action.environment_digest,
        ):
            raise ValueError("action features do not belong to state")
        self._encoder.validate_features(state)
        self._encoder.validate_features(action)
        with self._lock:
            return float(self._online.predict(self._rows(state, (action,)))[0])

    def scores(self, decision: EncodedDecision) -> dict[str, float]:
        return self._scores(EncodedDecision.from_json(decision.to_json()))

    def _scores(self, decision: EncodedDecision) -> dict[str, float]:
        actions = self._validate_decision(decision)
        if not actions:
            return {}
        with self._lock:
            predicted = self._online.predict(self._rows(decision.state, actions))
        return {
            action.candidate_id: float(score)
            for action, score in zip(actions, predicted, strict=True)
        }

    def rank(self, decision: EncodedDecision) -> tuple[str, ...]:
        scores = self.scores(decision)
        return tuple(sorted(scores, key=lambda key: (-scores[key], key)))

    def behavior_scores(
        self,
        decision: EncodedDecision,
        *,
        memory: ReturnLookup | None = None,
        retrieval_weight: float = 0.0,
        before_step: int | None = None,
        exclude_episode: str | None = None,
    ) -> dict[str, float]:
        """Blend only verified returns for concrete, currently eligible IDs."""
        if not 0.0 <= retrieval_weight <= 1.0:
            raise ValueError("retrieval weight must be between zero and one")
        decision = EncodedDecision.from_json(decision.to_json())
        scores = self._scores(decision)
        if memory is None or retrieval_weight == 0.0 or not scores:
            return scores
        if before_step is not None and (
            type(before_step) is not int or before_step < 0
        ):
            raise ValueError("retrieval cutoff must be a nonnegative integer")
        metadata = self._checkpoint_metadata
        if metadata is not None:
            from ai4algebra.memory import FrozenReturnMemory

            if (
                not isinstance(memory, FrozenReturnMemory)
                or (memory.artifact_digest, memory.cutoff)
                != (metadata.memory_digest, metadata.memory_cutoff)
                or (before_step is not None and before_step != memory.cutoff)
            ):
                raise ValueError(
                    "return memory does not match frozen checkpoint snapshot"
                )
            before_step = memory.cutoff
        if before_step is None or not exclude_episode:
            raise ValueError(
                "retrieval requires a decision cutoff and excluded episode"
            )
        returns = memory.query(
            decision.state,
            decision.candidate_set,
            before_step=before_step,
            exclude_episode=exclude_episode,
        )
        for key in scores.keys() & returns.keys():
            realized = returns[key]
            if not isfinite(realized):
                raise ValueError("matched return must be finite")
            scores[key] = (1.0 - retrieval_weight) * scores[
                key
            ] + retrieval_weight * realized
        return scores

    def select(
        self,
        decision: EncodedDecision,
        *,
        epsilon: float = 0.0,
        rng: Generator | None = None,
        memory: ReturnLookup | None = None,
        retrieval_weight: float = 0.0,
        before_step: int | None = None,
        exclude_episode: str | None = None,
    ) -> str | None:
        if not 0.0 <= epsilon <= 1.0:
            raise ValueError("epsilon must be between zero and one")
        if epsilon > 0.0 and rng is None:
            raise ValueError("exploration requires a caller-owned RNG")
        scores = self.behavior_scores(
            decision,
            memory=memory,
            retrieval_weight=retrieval_weight,
            before_step=before_step,
            exclude_episode=exclude_episode,
        )
        if not scores:
            return None
        if rng is not None and epsilon > 0.0 and rng.random() < epsilon:
            return sorted(scores)[int(rng.integers(len(scores)))]
        return min(scores, key=lambda key: (-scores[key], key))

    def targets(self, batch: Sequence[LearningSample]) -> TargetBatch:
        """Select with the online network and evaluate the selected successor only."""
        samples = tuple(LearningSample.from_json(sample.to_json()) for sample in batch)
        with self._lock:
            return self._targets(samples)

    def _targets(self, samples: Sequence[LearningSample]) -> TargetBatch:
        values: list[float | None] = []
        selected: list[str | None] = []
        missing = unavailable = truncations = 0
        for sample in samples:
            self._validate_decision(sample.decision)
            successor = sample.next_decision
            actions = () if successor is None else self._validate_decision(successor)
            if sample.terminated:
                values.append(sample.reward)
                selected.append(None)
                continue
            if successor is None:
                missing += 1
                values.append(None)
                selected.append(None)
                continue
            if not actions:
                unavailable += 1
                values.append(None)
                selected.append(None)
                continue
            scores = self._online.predict(self._rows(successor.state, actions))
            action, _ = min(
                zip(actions, scores, strict=True),
                key=lambda pair: (-pair[1], pair[0].candidate_id),
            )
            next_q = float(
                self._target.predict(self._rows(successor.state, (action,)))[0]
            )
            value = sample.reward + self.config.gamma * next_q
            if not isfinite(value):
                raise FloatingPointError("Bellman target must remain finite")
            values.append(value)
            selected.append(action.candidate_id)
            truncations += int(sample.truncated)
        return TargetBatch(
            tuple(values), tuple(selected), missing, unavailable, truncations
        )

    def update(self, batch: Sequence[LearningSample]) -> UpdateMetrics:
        if self.frozen:
            raise TypeError("evaluation checkpoint is frozen")
        samples = tuple(LearningSample.from_json(sample.to_json()) for sample in batch)
        if not samples:
            raise ValueError("update requires a nonempty training batch")
        with self._lock:
            targets = self._targets(samples)
            rows = []
            values = []
            for sample, value in zip(samples, targets.values, strict=True):
                if value is not None:
                    rows.append(
                        sample.decision.state.values + sample.chosen_action.values
                    )
                    values.append(value)
            loss = target_mean = None
            synced = False
            if values:
                target_mean = mean(values)
                loss = self._online.train(
                    np.array(rows, np.float64),
                    np.array(values, np.float64),
                    self.config.learning_rate,
                )
                self._update_steps += 1
                synced = self.update_steps % self.config.target_update_interval == 0
                if synced:
                    self._target = self._online.copy()
            return UpdateMetrics(
                loss=loss,
                target_mean=target_mean,
                used_samples=len(values),
                missing_next_observations=targets.missing_next_observations,
                no_eligible_next_actions=targets.no_eligible_next_actions,
                bootstrapped_truncations=targets.bootstrapped_truncations,
                update_steps=self.update_steps,
                target_synced=synced,
            )

    def save(self, path: str | Path, metadata: CheckpointMetadata) -> str:
        metadata = CheckpointMetadata.from_json(metadata.to_json())
        if metadata.policy_digest != self.policy_digest:
            raise ValueError(
                "checkpoint metadata candidate policy does not match learner"
            )
        if (
            self._checkpoint_metadata is not None
            and metadata != self._checkpoint_metadata
        ):
            raise ValueError("cannot change frozen checkpoint metadata")
        with self._lock:
            artifact = EvaluationArtifact(
                kind="ai4algebra-ddqn-evaluation-v1",
                config=self.config,
                encoder_config=self._encoder.config,
                encoder_digest=self._encoder.encoder_digest,
                metadata=metadata,
                online=self._online.snapshot(),
                target=self._target.snapshot(),
                update_steps=self.update_steps,
            )
        artifact.write(Path(path))
        return artifact.artifact_digest

    @classmethod
    def load(
        cls,
        path: str | Path,
        *,
        encoder: FeatureEncoder,
        expected_metadata: CheckpointMetadata,
        expected_artifact_digest: str | None = None,
    ) -> Self:
        artifact = EvaluationArtifact.from_json(Path(path).read_bytes())
        expected_metadata = CheckpointMetadata.from_json(expected_metadata.to_json())
        if (
            expected_artifact_digest is not None
            and artifact.artifact_digest != expected_artifact_digest
        ):
            raise ValueError("checkpoint differs from the expected artifact digest")
        if artifact.metadata != expected_metadata:
            raise ValueError(
                "checkpoint run, policy, corpus, source or memory does not match"
            )
        if (artifact.encoder_config, artifact.encoder_digest) != (
            encoder.config,
            encoder.encoder_digest,
        ):
            raise ValueError("checkpoint encoder does not match")
        input_size = encoder.state_size + encoder.action_size
        online = ScalarQ.restore(
            artifact.online, input_size, artifact.config.hidden_size
        )
        target = ScalarQ.restore(
            artifact.target, input_size, artifact.config.hidden_size
        )
        for array in (
            online.weights,
            online.bias,
            online.readout,
            target.weights,
            target.bias,
            target.readout,
        ):
            array.setflags(write=False)
        learner = cls(encoder, artifact.metadata.policy_digest, artifact.config)
        learner._online = online
        learner._target = target
        learner._update_steps = artifact.update_steps
        learner._checkpoint_metadata = artifact.metadata
        return learner
