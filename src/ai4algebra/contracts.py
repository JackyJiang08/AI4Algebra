"""Versioned, immutable records exchanged by the proof loop."""

import hashlib
import json
from pathlib import PureWindowsPath
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationInfo,
    field_validator,
    model_validator,
)
from typing_extensions import Self

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:/-]+$")]
NonBlank = Annotated[str, StringConstraints(pattern=r"\S")]
_IDENTIFIER_ADAPTER = TypeAdapter[Identifier](Identifier)


def _reject_admission(name: str) -> str:
    if name.rsplit(".", 1)[-1] in {"sorry", "admit", "sorryAx"}:
        raise ValueError("admission is not a declaration operand")
    return name


LeanName = Annotated[
    str,
    StringConstraints(
        pattern=r"^[\p{L}_][\p{L}\p{N}\p{M}_']*(\.[\p{L}_][\p{L}\p{N}\p{M}_']*)*$"
    ),
    AfterValidator(_reject_admission),
]
_LEAN_NAME_ADAPTER = TypeAdapter[LeanName](LeanName)
Split = Literal["train", "validation", "test"]


def digest_json(value: object) -> str:
    """Hash canonical UTF-8 JSON, preserving sequence order."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for name, value in pairs:
        if name in fields:
            raise ValueError("duplicate JSON field")
        fields[name] = value
    return fields


class Record(BaseModel):
    """Common settings for persisted and process-boundary records."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        allow_inf_nan=False,
        validate_default=True,
    )
    schema_version: Literal[1] = 1

    @field_validator("schema_version", mode="before")
    @classmethod
    def _check_version(cls, version: object) -> object:
        if type(version) is not int or version != 1:
            raise ValueError("unsupported schema version")
        return version

    @model_validator(mode="after")
    def _check_wire_identity(self, info: ValidationInfo) -> Self:
        if info.mode == "json":
            if "schema_version" not in self.model_fields_set:
                raise ValueError("missing schema version")
            for name, field in type(self).model_fields.items():
                if (
                    field.description == _COMPUTED_DIGEST
                    and name not in self.model_fields_set
                ):
                    raise ValueError(f"missing {name}")
        return self

    @classmethod
    def from_json(cls, data: str | bytes) -> Self:
        json.loads(data, object_pairs_hook=_unique_fields)
        return cls.model_validate_json(data)

    def to_json(self) -> str:
        return self.model_dump_json()


_COMPUTED_DIGEST = "Computed from the immutable record contents."


def _set_digest(record: Record, name: str, supplied: str, data: object) -> None:
    calculated = digest_json(data)
    if supplied and supplied != calculated:
        raise ValueError(f"{name} does not match the record")
    object.__setattr__(record, name, calculated)


class SourceRef(Record):
    kind: Identifier
    source_id: Identifier
    revision: Identifier
    location: NonBlank
    content_digest: Digest
    attribution: NonBlank
    license_ref: NonBlank

    @field_validator("location")
    @classmethod
    def _validate_location(cls, value: str) -> str:
        path = PureWindowsPath(value)
        if (
            path.anchor
            or not path.parts
            or any(part.endswith((".", " ")) or ":" in part for part in path.parts)
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError(
                "source location must be a relative path without traversal"
            )
        return value


class Problem(Record):
    task_id: Identifier
    source: SourceRef
    informal_statement: NonBlank
    family_id: Identifier
    split: Split
    imports: tuple[LeanName, ...]
    lean_name: LeanName
    lean_statement: NonBlank
    mapping_evidence_id: Identifier
    universes: tuple[LeanName, ...] = ()
    binders: tuple[NonBlank, ...] = ()
    statement_digest: Digest = Field(
        default="", validate_default=False, description=_COMPUTED_DIGEST
    )

    @model_validator(mode="after")
    def _validate_statement(self) -> Self:
        if len(set(self.imports)) != len(self.imports):
            raise ValueError("duplicate imports")
        if len(set(self.universes)) != len(self.universes):
            raise ValueError("duplicate universes")
        _set_digest(
            self,
            "statement_digest",
            self.statement_digest,
            (
                self.schema_version,
                self.lean_name,
                self.imports,
                self.universes,
                self.binders,
                self.lean_statement,
            ),
        )
        return self


class Hypothesis(Record):
    local_id: Identifier
    binder_kind: Literal["explicit", "implicit", "strict_implicit", "instance"]
    name: NonBlank
    type_text: NonBlank
    expression: NonBlank
    value: NonBlank | None = None


class Goal(Record):
    goal_id: Identifier
    target: NonBlank
    expression: NonBlank
    hypotheses: tuple[Hypothesis, ...] = ()

    @model_validator(mode="after")
    def _validate_local_ids(self) -> Self:
        if len({hyp.local_id for hyp in self.hypotheses}) != len(self.hypotheses):
            raise ValueError("duplicate local IDs in goal")
        return self


class Snapshot(Record):
    session_id: Identifier
    environment_digest: Digest
    prefix_digest: Digest
    snapshot_id: Identifier


class Observation(Record):
    snapshot: Snapshot
    goals: tuple[Goal, ...]
    expression_version: Identifier = "lean-expr-v1"
    state_digest: Digest = Field(
        default="", validate_default=False, description=_COMPUTED_DIGEST
    )

    @model_validator(mode="after")
    def _validate_goal_ids(self) -> Self:
        if len({goal.goal_id for goal in self.goals}) != len(self.goals):
            raise ValueError("duplicate goal IDs in observation")
        _set_digest(
            self,
            "state_digest",
            self.state_digest,
            (
                self.schema_version,
                self.snapshot.environment_digest,
                self.snapshot.prefix_digest,
                self.expression_version,
                tuple(goal.model_dump(mode="json") for goal in self.goals),
            ),
        )
        return self


class Argument(Record):
    kind: Literal["local", "lemma"]
    reference: NonBlank

    @model_validator(mode="after")
    def _validate_lemma_name(self) -> Self:
        if self.kind == "lemma":
            _LEAN_NAME_ADAPTER.validate_python(self.reference)
        else:
            _IDENTIFIER_ADAPTER.validate_python(self.reference)
        return self


Operation = Literal[
    "decide",
    "assumption",
    "reflexivity",
    "intro",
    "constructor",
    "exact",
    "apply",
    "rewrite",
    "simp_only",
]


class Candidate(Record):
    operation: Operation
    goal_id: Identifier
    lemma: LeanName | None = None
    local_id: Identifier | None = None
    arguments: tuple[Argument, ...] = ()
    direction: Literal["forward", "backward"] = "forward"
    location: Identifier | None = None
    simp_lemmas: tuple[LeanName, ...] = ()
    provenance: Identifier = "deterministic"
    generator_version: Identifier = "1"
    candidate_id: Digest = Field(
        default="", validate_default=False, description=_COMPUTED_DIGEST
    )

    @model_validator(mode="after")
    def _validate_operation(self) -> Self:
        has_operand = self.lemma is not None or self.local_id is not None
        if self.lemma is not None and self.local_id is not None:
            raise ValueError("lemma and local operands are mutually exclusive")
        if (self.operation in {"exact", "apply", "rewrite"}) != has_operand:
            raise ValueError("invalid operand for operation")
        if self.arguments and (
            self.lemma is None or self.operation not in {"exact", "apply"}
        ):
            raise ValueError("arguments require exact or apply with a lemma")
        if self.operation != "rewrite" and (
            self.location is not None or self.direction != "forward"
        ):
            raise ValueError("location and direction require rewrite")
        if (self.operation == "simp_only") != bool(self.simp_lemmas):
            raise ValueError("simp_only requires an explicit lemma list")
        if len(set(self.simp_lemmas)) != len(self.simp_lemmas):
            raise ValueError("duplicate simp lemma")
        _set_digest(
            self,
            "candidate_id",
            self.candidate_id,
            self.model_dump(mode="json", exclude={"candidate_id", "provenance"}),
        )
        return self


class CandidateSet(Record):
    state_digest: Digest
    policy_digest: Digest
    candidates: tuple[Candidate, ...]
    eligible: tuple[bool, ...]
    generation_status: Literal["ok", "fallback", "budget_exhausted", "unavailable"] = (
        "ok"
    )

    @model_validator(mode="after")
    def _validate_mask(self) -> Self:
        if len(self.candidates) != len(self.eligible):
            raise ValueError("candidate and eligibility counts differ")
        if len({item.candidate_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("duplicate candidate IDs")
        return self

    def _is_eligible(self, candidate_id: str) -> bool:
        return any(
            eligible and item.candidate_id == candidate_id
            for item, eligible in zip(self.candidates, self.eligible, strict=True)
        )

    def validate_for(self, observation: Observation) -> None:
        """Check eligible candidate references against the originating observation."""
        if self.state_digest != observation.state_digest:
            raise ValueError("candidate set does not belong to observation")
        goals = {goal.goal_id: goal for goal in observation.goals}
        for candidate, eligible in zip(self.candidates, self.eligible, strict=True):
            if not eligible:
                continue
            goal = goals.get(candidate.goal_id)
            if goal is None:
                raise ValueError("candidate refers to an unknown goal")
            locals_ = {hyp.local_id for hyp in goal.hypotheses}
            references = {
                arg.reference for arg in candidate.arguments if arg.kind == "local"
            }
            if candidate.local_id is not None:
                references.add(candidate.local_id)
            if candidate.location is not None:
                references.add(candidate.location)
            if not references <= locals_:
                raise ValueError("candidate refers to an unknown local")


class StepResult(Record):
    status: Literal["advanced", "closed", "rejected", "timeout", "infrastructure_error"]
    snapshot: Snapshot | None = None
    observation: Observation | None = None
    diagnostics: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def _validate_observation(self) -> Self:
        observation = self.observation
        if (self.snapshot is None) != (observation is None):
            raise ValueError("snapshot and observation must be supplied together")
        if observation is not None and self.snapshot != observation.snapshot:
            raise ValueError("step observation belongs to a different snapshot")
        if self.status == "advanced" and (observation is None or not observation.goals):
            raise ValueError("advanced step requires a remaining goal")
        if self.status == "closed" and (observation is None or observation.goals):
            raise ValueError("closed step requires an actual empty observation")
        return self


class Certificate(Record):
    task_id: Identifier
    statement_digest: Digest
    environment_digest: Digest
    source_digest: Digest
    policy_digest: Digest
    eligibility_digest: Digest | None = None
    imports: tuple[LeanName, ...]
    steps: tuple[Candidate, ...]
    proof: NonBlank
    proof_digest: Digest = Field(
        default="", validate_default=False, description=_COMPUTED_DIGEST
    )

    @model_validator(mode="after")
    def _validate_proof(self) -> Self:
        _set_digest(
            self, "proof_digest", self.proof_digest, (self.schema_version, self.proof)
        )
        return self


class Verdict(Record):
    status: Literal["accepted", "rejected", "indeterminate"]
    replay_passed: bool | None
    type_passed: bool | None
    axioms_passed: bool | None
    dependencies_passed: bool | None
    lean_version: NonBlank
    mathlib_revision: NonBlank
    # Hash of the full certificate's canonical JSON payload, issued by the verifier.
    certificate_digest: Digest | None = None
    axioms: tuple[NonBlank, ...] = ()
    dependencies: tuple[NonBlank, ...] = ()
    diagnostics: tuple[NonBlank, ...] = ()

    @model_validator(mode="after")
    def _validate_acceptance(self) -> Self:
        checks = (
            self.replay_passed,
            self.type_passed,
            self.axioms_passed,
            self.dependencies_passed,
        )
        if self.status == "accepted" and not all(checks):
            raise ValueError(
                "accepted verdict requires every verification check to pass"
            )
        return self


class Transition(Record):
    episode_id: Identifier
    branch_id: Identifier
    task_id: Identifier
    split: Split
    collection_step: Annotated[int, Field(ge=0)]
    observation: Observation
    candidate_set: CandidateSet
    chosen_candidate_id: Digest
    reward: float
    next_observation: Observation
    next_candidate_set: CandidateSet
    terminated: bool
    truncated: bool
    outcome: Identifier
    feature_version: Identifier

    @model_validator(mode="after")
    def _validate_successor(self) -> Self:
        if self.split != "train":
            raise ValueError("learning transitions must originate from the train split")
        self.candidate_set.validate_for(self.observation)
        self.next_candidate_set.validate_for(self.next_observation)
        if self.candidate_set.policy_digest != self.next_candidate_set.policy_digest:
            raise ValueError("candidate policy changed within transition")
        if not self.candidate_set._is_eligible(self.chosen_candidate_id):
            raise ValueError("chosen candidate is not eligible")
        parent = self.observation.snapshot
        successor = self.next_observation.snapshot
        if (parent.session_id, parent.environment_digest) != (
            successor.session_id,
            successor.environment_digest,
        ):
            raise ValueError("successor belongs to another session or environment")
        if self.terminated:
            if (
                self.truncated
                or self.outcome != "verified"
                or self.next_observation.goals
            ):
                raise ValueError(
                    "terminal transition requires verified closure without truncation"
                )
        else:
            if self.outcome == "verified":
                raise ValueError("verified outcome requires a terminal transition")
            if not self.next_observation.goals or not any(
                self.next_candidate_set.eligible
            ):
                raise ValueError(
                    "nonterminal transition requires eligible continuation candidates"
                )
            if self.outcome == "rejected":
                if self.next_observation.state_digest != self.observation.state_digest:
                    raise ValueError(
                        "rejected action requires an unchanged observation"
                    )
                if self.next_candidate_set._is_eligible(self.chosen_candidate_id):
                    raise ValueError(
                        "rejected action must be excluded from eligible continuation"
                    )
        return self
