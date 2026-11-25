"""Deterministic features for state/action scoring and approximate retrieval."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from itertools import islice
from typing import Annotated, Literal, TypedDict

from pydantic import Field, model_validator
from typing_extensions import Self

from ai4algebra.contracts import (
    Candidate,
    Digest,
    Goal,
    LeanName,
    NonBlank,
    Observation,
    Operation,
    Record,
    digest_json,
)
from ai4algebra.representation._expression import Normalizer, Term

_OPERATIONS: tuple[Operation, ...] = (
    "assumption",
    "reflexivity",
    "intro",
    "constructor",
    "exact",
    "apply",
    "rewrite",
    "simp_only",
)
_STATE_SCALARS = 8
_ACTION_SCALARS = len(_OPERATIONS) + 8
_Count = Annotated[int, Field(ge=0)]


class EncoderConfig(Record):
    """Frozen feature widths, token budget and deterministic hash seed."""

    version: Literal["hashed-lean-v1"] = "hashed-lean-v1"
    expression_version: Literal["lean-expr-v1"] = "lean-expr-v1"
    state_buckets: Annotated[int, Field(gt=0, le=65536)] = 128
    action_buckets: Annotated[int, Field(gt=0, le=65536)] = 64
    max_tokens: Annotated[int, Field(gt=0, le=1_000_000)] = 4096
    hash_seed: Annotated[int, Field(ge=0, le=2**64 - 1)] = 0


class DecisionContext(Record):
    remaining_depth: _Count
    remaining_steps: _Count | None = None
    eligible_count: _Count | None = None


class DeclarationSignature(Record):
    """A permitted declaration's type in the observer's expression format."""

    name: LeanName
    expression: NonBlank


class CandidateContext(Record):
    """Metadata received from the eligible index or from a pre-decision probe."""

    declarations: tuple[DeclarationSignature, ...] = ()
    side_goals: tuple[Goal, ...] = ()


class _Features(Record):
    encoder_digest: Digest
    state_digest: Digest
    environment_digest: Digest
    semantic_digest: Digest
    feature_digest: Digest
    provenance_digest: Digest
    values: Annotated[tuple[float, ...], Field(min_length=1)]
    overflow: bool

    @model_validator(mode="after")
    def _verify_digests(self) -> Self:
        if self.feature_digest != _hash_features(
            type(self).__name__, self.encoder_digest, self.values
        ):
            raise ValueError("feature digest does not match vector")
        if self.provenance_digest != _hash_provenance(
            type(self).__name__, self.model_dump(mode="json")
        ):
            raise ValueError("feature provenance digest does not match metadata")
        return self


class StateFeatures(_Features):
    """A state vector and its observation provenance."""


class ActionFeatures(_Features):
    """A candidate vector and its originating observation and action identifiers."""

    candidate_id: Digest


def _scale(count: int) -> float:
    return count / (count + 1)


def _tokens(term: Term) -> Iterator[str | int | bool]:
    if isinstance(term, tuple):
        yield "["
        for item in term:
            yield from _tokens(item)
        yield "]"
    elif isinstance(term, str):
        yield "s" + term
    else:
        yield term


def _hash_features(kind: str, encoder_digest: str, values: tuple[float, ...]) -> str:
    return digest_json((kind, encoder_digest, values))


def _hash_provenance(kind: str, fields: Mapping[str, object]) -> str:
    # The vector digest already commits to values and preserves vector equality.
    metadata = {
        name: value
        for name, value in fields.items()
        if name not in {"values", "provenance_digest"}
    }
    return digest_json((kind, metadata))


class _FeatureFields(TypedDict):
    schema_version: Literal[1]
    encoder_digest: str
    state_digest: str
    environment_digest: str
    semantic_digest: str
    feature_digest: str
    values: tuple[float, ...]
    overflow: bool


def _feature_fields(
    kind: str,
    observation: Observation,
    encoder_digest: str,
    semantic_digest: str,
    values: tuple[float, ...],
    overflow: bool,
) -> _FeatureFields:
    return {
        "schema_version": 1,
        "encoder_digest": encoder_digest,
        "state_digest": observation.state_digest,
        "environment_digest": observation.snapshot.environment_digest,
        "semantic_digest": semantic_digest,
        "feature_digest": _hash_features(kind, encoder_digest, values),
        "values": values,
        "overflow": overflow,
    }


def is_approximate_collision(
    first: StateFeatures | ActionFeatures, second: StateFeatures | ActionFeatures
) -> bool:
    """Detect equal vectors for distinct semantic inputs under the same encoder."""
    first = type(first).from_json(first.to_json())
    second = type(second).from_json(second.to_json())
    return (
        type(first) is type(second)
        and first.encoder_digest == second.encoder_digest
        and first.values == second.values
        and first.semantic_digest != second.semantic_digest
    )


@dataclass(frozen=True)
class FeatureEncoder:
    """A fixed encoder usable on compatible training and evaluation observations."""

    config: EncoderConfig = EncoderConfig()

    @property
    def encoder_digest(self) -> str:
        return digest_json(self.config.model_dump(mode="json"))

    @property
    def state_size(self) -> int:
        return _STATE_SCALARS + self.config.state_buckets

    @property
    def action_size(self) -> int:
        return _ACTION_SCALARS + self.config.action_buckets

    def _check_expression_version(self, observation: Observation) -> None:
        if observation.expression_version != self.config.expression_version:
            raise ValueError("unsupported observation expression version")

    def _buckets(self, term: Term, width: int) -> tuple[tuple[float, ...], bool]:
        counts = [0] * width
        seen = 0
        overflow = False
        for position, token in enumerate(
            islice(_tokens(term), self.config.max_tokens + 1)
        ):
            if position == self.config.max_tokens:
                overflow = True
                break
            hashed = int(digest_json((self.config.hash_seed, position, token))[:16], 16)
            index = (hashed >> 1) % width
            counts[index] += 1 if hashed & 1 else -1
            seen += 1
        return tuple(count / max(1, seen) for count in counts), overflow

    def encode_state(
        self, observation: Observation, context: DecisionContext
    ) -> StateFeatures:
        """Hash every goal and its ordered local declarations under a fixed token budget."""
        self._check_expression_version(observation)
        term = Normalizer().goals(observation.goals)
        counts, overflow = self._buckets(term, self.config.state_buckets)
        values = (
            _scale(len(observation.goals)),
            _scale(sum(len(goal.hypotheses) for goal in observation.goals)),
            _scale(context.remaining_depth),
            _scale(context.remaining_steps or 0),
            float(context.remaining_steps is not None),
            _scale(context.eligible_count or 0),
            float(context.eligible_count is not None),
            float(overflow),
            *counts,
        )
        fields = _feature_fields(
            "StateFeatures",
            observation,
            self.encoder_digest,
            digest_json(
                (
                    observation.expression_version,
                    observation.snapshot.environment_digest,
                    term,
                    context.model_dump(mode="json"),
                )
            ),
            values,
            overflow,
        )
        return StateFeatures(
            **fields, provenance_digest=_hash_provenance("StateFeatures", fields)
        )

    def encode_candidate(
        self,
        candidate: Candidate,
        observation: Observation,
        context: CandidateContext | None = None,
    ) -> ActionFeatures:
        """Encode concrete operands, eligible type signatures and available side goals."""
        self._check_expression_version(observation)
        context = CandidateContext() if context is None else context
        goals = {
            goal.goal_id: (index, goal) for index, goal in enumerate(observation.goals)
        }
        focus = goals.get(candidate.goal_id)
        if focus is None:
            raise ValueError("candidate refers to an unknown goal")
        goal_index, goal = focus
        term = _candidate_term(candidate, goal, context)
        counts, overflow = self._buckets((goal_index, term), self.config.action_buckets)
        values = (
            *(float(candidate.operation == operation) for operation in _OPERATIONS),
            _scale(goal_index),
            _scale(len(candidate.arguments)),
            _scale(len(candidate.simp_lemmas)),
            _scale(len(context.side_goals)),
            _scale(len(context.declarations)),
            float(candidate.direction == "backward"),
            float(candidate.location is not None),
            float(overflow),
            *counts,
        )
        fields = _feature_fields(
            "ActionFeatures",
            observation,
            self.encoder_digest,
            digest_json(
                (
                    observation.expression_version,
                    observation.snapshot.environment_digest,
                    goal_index,
                    term,
                )
            ),
            values,
            overflow,
        )
        return ActionFeatures(
            **fields,
            candidate_id=candidate.candidate_id,
            provenance_digest=_hash_provenance(
                "ActionFeatures", {**fields, "candidate_id": candidate.candidate_id}
            ),
        )

    def validate_features(self, features: StateFeatures | ActionFeatures) -> None:
        """Require the checkpoint's encoder identity and vector dimensions."""
        if features.encoder_digest != self.encoder_digest:
            raise ValueError("feature encoder identity does not match")
        size = (
            self.state_size if isinstance(features, StateFeatures) else self.action_size
        )
        if len(features.values) != size:
            raise ValueError("feature vector width does not match encoder")
        type(features).from_json(features.to_json())


def _candidate_term(
    candidate: Candidate, goal: Goal, context: CandidateContext
) -> Term:
    positions = {hyp.local_id: index for index, hyp in enumerate(goal.hypotheses)}
    declarations = {item.name: item.expression for item in context.declarations}
    referenced = {*candidate.simp_lemmas}
    referenced.update(
        arg.reference for arg in candidate.arguments if arg.kind == "lemma"
    )
    if candidate.lemma is not None:
        referenced.add(candidate.lemma)
    if (
        len(declarations) != len(context.declarations)
        or declarations.keys() - referenced
    ):
        raise ValueError(
            "candidate metadata must uniquely describe referenced declarations"
        )

    normalizer = Normalizer()

    def local(reference: str) -> Term:
        index = positions.get(reference)
        if index is None:
            raise ValueError("candidate refers to an unknown local in the focused goal")
        type_ = normalizer.expr(goal.hypotheses[index].expression, local_count=index)
        return ("local", index, type_)

    def lemma(name: str) -> Term:
        source = declarations.get(name)
        return (
            "lemma",
            name,
            () if source is None else Normalizer().expr(source, local_count=0),
        )

    return (
        candidate.operation,
        () if candidate.lemma is None else lemma(candidate.lemma),
        () if candidate.local_id is None else local(candidate.local_id),
        tuple(
            local(arg.reference) if arg.kind == "local" else lemma(arg.reference)
            for arg in candidate.arguments
        ),
        candidate.direction,
        () if candidate.location is None else local(candidate.location),
        tuple(lemma(name) for name in candidate.simp_lemmas),
        Normalizer().goals(context.side_goals),
    )


_DEFAULT_ENCODER = FeatureEncoder()


def encode_state(observation: Observation, context: DecisionContext) -> StateFeatures:
    return _DEFAULT_ENCODER.encode_state(observation, context)


def encode_candidate(
    candidate: Candidate,
    observation: Observation,
    context: CandidateContext | None = None,
) -> ActionFeatures:
    return _DEFAULT_ENCODER.encode_candidate(candidate, observation, context)
