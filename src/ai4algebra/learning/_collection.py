"""Persist actual encoded proof decisions at collection time."""

from collections.abc import Mapping

from pydantic import model_validator
from typing_extensions import Self

from ai4algebra.contracts import Problem, Transition
from ai4algebra.memory._records import MemoryArchive, TrainingTrace
from ai4algebra.representation import EncoderConfig, FeatureEncoder

from ._records import EncodedDecision, LearningSample


class CollectedSample(MemoryArchive):
    """A source-bound training sample with its original features and contexts.

    Capture at each executed training step, while both decision contexts are
    available. Persist ``to_json()`` and its digest in the collection manifest.
    Offline training calls ``restore()`` and passes the restored ``sample``
    to the learner, using the stored vectors and masks directly.
    """

    trace: TrainingTrace
    sample: LearningSample
    encoder_config: EncoderConfig

    @model_validator(mode="after")
    def _check_trace(self) -> Self:
        transition = self.trace.transition
        sample = self.sample
        if sample != LearningSample.from_transition(
            transition, sample.decision, sample.next_decision
        ):
            raise ValueError("learning sample does not match recorded transition")
        encoder = FeatureEncoder(self.encoder_config)
        for decision, observation in (
            (sample.decision, transition.observation),
            (sample.next_decision, transition.next_observation),
        ):
            if decision is None:
                continue
            if decision.state != encoder.encode_state(observation, decision.context):
                raise ValueError(
                    "state features do not match recorded decision context"
                )
            for action in decision.eligible_actions:
                encoder.validate_features(action)
        return self

    @classmethod
    def capture(
        cls,
        transition: Transition,
        decision: EncodedDecision,
        next_decision: EncodedDecision | None,
        *,
        encoder: FeatureEncoder,
        task_sources: Mapping[str, Problem],
    ) -> Self:
        trace = TrainingTrace.capture(transition, task_sources)
        sample = LearningSample.from_transition(
            trace.transition, decision, next_decision
        )
        return cls(
            trace=trace,
            sample=sample,
            encoder_config=EncoderConfig.from_json(encoder.config.to_json()),
        )

    @classmethod
    def restore(
        cls,
        data: str | bytes,
        *,
        task_sources: Mapping[str, Problem],
        expected_artifact_digest: str | None = None,
    ) -> Self:
        collected = cls.from_json(data)
        if (
            expected_artifact_digest is not None
            and collected.artifact_digest != expected_artifact_digest
        ):
            raise ValueError(
                "collected sample differs from the expected artifact digest"
            )
        collected.trace.validate_source(task_sources)
        return collected
