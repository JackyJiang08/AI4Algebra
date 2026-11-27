"""Immutable decisions and metadata for candidate-conditioned learning."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal, cast

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)
from typing_extensions import Self

from ai4algebra.contracts import (
    CandidateSet,
    Digest,
    Identifier,
    Observation,
    Record,
    Split,
    Transition,
)
from ai4algebra.representation import (
    ActionFeatures,
    CandidateContext,
    DecisionContext,
    FeatureEncoder,
    StateFeatures,
)

NonnegativeInt = Annotated[int, Field(ge=0)]
Activation = Literal["silu", "relu"]


class DDQNConfig(Record):
    hidden_size: Annotated[int, Field(gt=0)] = 32
    hidden_layers: Annotated[int, Field(gt=0)] = 3
    activation: Activation = "silu"
    gamma: Annotated[float, Field(ge=0, le=1)] = 0.99
    learning_rate: Annotated[float, Field(gt=0)] = 0.01
    target_update_interval: Annotated[int, Field(gt=0)] | None = None
    seed: NonnegativeInt = 0
    huber_delta: Annotated[float, Field(gt=0)] | None = None
    tau: Annotated[float, Field(gt=0, le=1)] | None = 0.01

    @model_validator(mode="before")
    @classmethod
    def _legacy_defaults(cls, value: object) -> object:
        if isinstance(value, dict):
            if value.get("target_update_interval") is not None and "tau" not in value:
                value = {**value, "tau": None}
            if "schema_version" in value and not (
                {"hidden_layers", "activation"} & value.keys()
            ):
                value = {**value, "hidden_layers": 1, "activation": "relu"}
        return value

    @model_validator(mode="after")
    def _validate_target_update(self) -> Self:
        if (self.tau is None) == (self.target_update_interval is None):
            raise ValueError("specify exactly one of tau and target_update_interval")
        return self

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data = cast(dict[str, object], handler(self))
        if self.activation == "relu" and self.hidden_layers == 1:
            # Archived single-layer checkpoints predate architecture fields.
            data.pop("activation", None)
            data.pop("hidden_layers", None)
        if self.huber_delta is None:
            # Preserve the serialized configuration and digest of MSE checkpoints.
            data.pop("huber_delta", None)
        if self.tau is None:
            # Historical hard-update checkpoints had no tau field.
            data.pop("tau", None)
        if self.target_update_interval is None:
            data.pop("target_update_interval", None)
        return data


class CheckpointMetadata(Record):
    """Run and immutable inputs associated with an evaluation checkpoint."""

    run_id: Identifier
    policy_digest: Digest
    corpus_digest: Digest
    source_digest: Digest
    run_manifest_digest: Digest | None = None
    memory_digest: Digest | None = None
    memory_cutoff: NonnegativeInt | None = None

    @model_validator(mode="after")
    def _check_memory(self) -> Self:
        if (self.memory_digest is None) != (self.memory_cutoff is None):
            raise ValueError(
                "evaluation memory digest and cutoff must be supplied together"
            )
        return self


class EncodedDecision(Record):
    """A decision's stored state, candidate IDs, mask and aligned action features."""

    state: StateFeatures
    context: DecisionContext
    candidate_set: CandidateSet
    actions: tuple[ActionFeatures | None, ...]

    @model_validator(mode="after")
    def _check_alignment(self) -> Self:
        if self.candidate_set.state_digest != self.state.state_digest:
            raise ValueError("candidate set does not belong to decision state")
        if len(self.actions) != len(self.candidate_set.candidates):
            raise ValueError("action feature count does not match candidate count")
        if (
            self.context.eligible_count is not None
            and self.context.eligible_count != sum(self.candidate_set.eligible)
        ):
            raise ValueError(
                "decision context eligible count does not match candidate mask"
            )
        for candidate, eligible, action in zip(
            self.candidate_set.candidates,
            self.candidate_set.eligible,
            self.actions,
            strict=True,
        ):
            if action is None:
                if eligible:
                    raise ValueError("eligible candidate is missing stored features")
            elif (
                action.candidate_id != candidate.candidate_id
                or action.encoder_digest != self.state.encoder_digest
                or action.state_digest != self.state.state_digest
                or action.environment_digest != self.state.environment_digest
            ):
                raise ValueError("action features do not belong to candidate and state")
        return self

    @property
    def eligible_actions(self) -> tuple[ActionFeatures, ...]:
        return tuple(
            action
            for action, allowed in zip(
                self.actions, self.candidate_set.eligible, strict=True
            )
            if allowed and action is not None
        )


def encode_decision(
    encoder: FeatureEncoder,
    observation: Observation,
    candidate_set: CandidateSet,
    context: DecisionContext,
    *,
    candidate_contexts: Mapping[str, CandidateContext] | None = None,
) -> EncodedDecision:
    """Capture features and eligibility for reuse without running the generator."""
    observation = Observation.from_json(observation.to_json())
    candidate_set = CandidateSet.from_json(candidate_set.to_json())
    context = DecisionContext.from_json(context.to_json())
    candidate_set.validate_for(observation)
    contexts = {} if candidate_contexts is None else candidate_contexts
    return EncodedDecision(
        state=encoder.encode_state(observation, context),
        context=context,
        candidate_set=candidate_set,
        actions=tuple(
            encoder.encode_candidate(
                candidate, observation, contexts.get(candidate.candidate_id)
            )
            if eligible
            else None
            for candidate, eligible in zip(
                candidate_set.candidates, candidate_set.eligible, strict=True
            )
        ),
    )


class LearningSample(Record):
    """A train decision and the encoded successor observed on the same branch."""

    decision: EncodedDecision
    chosen_candidate_id: Digest
    reward: float
    next_decision: EncodedDecision | None
    terminated: bool
    truncated: bool
    outcome: Identifier
    split: Split

    @property
    def chosen_action(self) -> ActionFeatures:
        for action in self.decision.eligible_actions:
            if action.candidate_id == self.chosen_candidate_id:
                return action
        raise ValueError("chosen candidate is not eligible")

    @model_validator(mode="after")
    def _check_decisions(self) -> Self:
        if self.split != "train":
            raise ValueError("learning samples must originate from the train split")
        self.chosen_action  # Validate that the chosen pair has stored eligible features.
        if self.terminated != (self.outcome == "verified") or (
            self.terminated and self.truncated
        ):
            raise ValueError("termination requires verified closure without truncation")
        successor = self.next_decision
        if successor is not None:
            if (
                successor.candidate_set.policy_digest
                != self.decision.candidate_set.policy_digest
                or successor.state.environment_digest
                != self.decision.state.environment_digest
                or successor.state.encoder_digest != self.decision.state.encoder_digest
            ):
                raise ValueError("successor policy, environment or encoder differs")
            if self.terminated and successor.eligible_actions:
                raise ValueError("verified closure cannot have eligible next actions")
        return self

    @classmethod
    def from_transition(
        cls,
        transition: Transition,
        decision: EncodedDecision,
        next_decision: EncodedDecision | None,
    ) -> Self:
        """Bind decisions at collection time, while their context is known.

        A raw transition alone does not preserve either decision's feature context.
        Persist the collection as a CollectedSample for offline training.
        """
        transition = Transition.from_json(transition.to_json())
        decision = EncodedDecision.from_json(decision.to_json())
        if next_decision is not None:
            next_decision = EncodedDecision.from_json(next_decision.to_json())
        if (
            decision.candidate_set != transition.candidate_set
            or decision.state.environment_digest
            != transition.observation.snapshot.environment_digest
            or decision.state.encoder_digest != transition.feature_version
        ):
            raise ValueError("decision does not match recorded transition")
        if next_decision is None:
            if not transition.terminated:
                raise ValueError(
                    "recorded continuation requires stored successor features"
                )
        elif next_decision.candidate_set != transition.next_candidate_set:
            raise ValueError("successor decision does not match recorded transition")
        return cls(
            decision=decision,
            chosen_candidate_id=transition.chosen_candidate_id,
            reward=transition.reward,
            next_decision=next_decision,
            terminated=transition.terminated,
            truncated=transition.truncated,
            outcome=transition.outcome,
            split=transition.split,
        )


@dataclass(frozen=True)
class TargetBatch:
    """One detached target/selection per input, with exclusions counted by reason."""

    values: tuple[float | None, ...]
    selected_candidate_ids: tuple[str | None, ...]
    missing_next_observations: int
    no_eligible_next_actions: int
    bootstrapped_truncations: int


@dataclass(frozen=True)
class UpdateMetrics:
    loss: float | None
    target_mean: float | None
    used_samples: int
    missing_next_observations: int
    no_eligible_next_actions: int
    bootstrapped_truncations: int
    update_steps: int
    # True when this optimizer step applied a soft update or a legacy hard copy.
    target_synced: bool
