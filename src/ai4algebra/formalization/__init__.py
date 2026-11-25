"""Versioned evidence for curated mathematical statements."""

from collections.abc import Callable
from typing import Annotated, Literal

from pydantic import Field, model_validator
from typing_extensions import Self

from ai4algebra.contracts import (
    Digest,
    Identifier,
    LeanName,
    NonBlank,
    Problem,
    Record,
    digest_json,
)

MappingStatus = Literal["curated_validated", "needs_review", "unsupported"]
CheckResult = Literal["definitionally_equal", "elaborated", "mismatch", "failed"]


class ReferenceType(Record):
    """Independently curated Lean telescope and conclusion for the source text."""

    universes: tuple[LeanName, ...]
    binders: tuple[NonBlank, ...]
    conclusion: NonBlank

    @property
    def digest(self) -> str:
        return digest_json(self.model_dump(mode="json"))


class Alignment(Record):
    kind: Literal["universe", "object", "assumption", "conclusion"]
    position: Annotated[int, Field(ge=0)]
    lean_fragment: NonBlank
    source_meaning: NonBlank


class Alias(Record):
    declaration: LeanName
    relationship: NonBlank
    basis: NonBlank


class StatementCheck(Record):
    """A check in a particular pinned Lean environment."""

    result: CheckResult
    environment_digest: Digest
    statement_digest: Digest
    reference_type_digest: Digest
    # Lean's hash of the elaborated reference expression with positional universe names.
    reference_type_key: Identifier | None = None
    detail: NonBlank

    @model_validator(mode="after")
    def _check_key(self) -> Self:
        if self.result == "definitionally_equal" and self.reference_type_key is None:
            raise ValueError(
                "a matched reference type requires its Lean expression key"
            )
        return self


class MappingEvidence(Record):
    evidence_id: Identifier
    task_id: Identifier
    source_digest: Digest
    statement_digest: Digest
    imports_digest: Digest
    status: MappingStatus
    status_reason: NonBlank
    reference_type: ReferenceType
    alignment: tuple[Alignment, ...]
    reviewer: NonBlank
    review_basis: NonBlank
    conventions: tuple[NonBlank, ...]
    source_scope: Literal["full", "subclaim"] = "full"
    source_scope_note: NonBlank | None = None
    reviewed_informal_digest: Digest | None = None
    target_declaration: LeanName
    aliases: tuple[Alias, ...] = ()
    check: StatementCheck | None = None

    @model_validator(mode="after")
    def _validate_review(self) -> Self:
        if (self.source_scope == "subclaim") != (self.source_scope_note is not None):
            raise ValueError("the explicit source scope and subclaim note must agree")
        reference = self.reference_type
        expected = {
            **{("universe", i): type_ for i, type_ in enumerate(reference.universes)},
            **{("binder", i): binder for i, binder in enumerate(reference.binders)},
            ("conclusion", 0): reference.conclusion,
        }
        actual = {
            (
                "binder" if row.kind in {"object", "assumption"} else row.kind,
                row.position,
            ): row.lean_fragment
            for row in self.alignment
        }
        if self.status == "curated_validated":
            if actual != expected or len(actual) != len(self.alignment):
                raise ValueError("validated mapping must align the full reference type")
            if self.check is None or self.check.result != "definitionally_equal":
                raise ValueError("validated mapping requires a checked reference type")
            if not self.conventions:
                raise ValueError("validated mapping requires mathematical conventions")
        if self.check is not None:
            if (
                self.check.statement_digest != self.statement_digest
                or self.check.reference_type_digest != reference.digest
            ):
                raise ValueError("statement check belongs to another type")
        if len(set(self.answer_declarations)) != len(self.answer_declarations):
            raise ValueError("duplicate target or equivalent declaration")
        return self

    @property
    def answer_declarations(self) -> tuple[str, ...]:
        return (self.target_declaration, *(item.declaration for item in self.aliases))

    def bind(self, problem: Problem, environment_digest: str) -> None:
        """Reject stale evidence and evidence for a different source or target."""
        if (
            problem.source.kind == "stacks-tag"
            and "source_scope" not in self.model_fields_set
        ):
            raise ValueError(
                f"Stacks mapping requires explicit source scope for task {problem.task_id}"
            )
        if (
            self.evidence_id != problem.mapping_evidence_id
            or self.task_id != problem.task_id
            or self.source_digest != problem.source.content_digest
            or self.statement_digest != problem.statement_digest
            or self.imports_digest != digest_json(problem.imports)
            or self.target_declaration != problem.lean_name
            or (
                (
                    problem.source.kind == "stacks-tag"
                    or self.reviewed_informal_digest is not None
                )
                and self.reviewed_informal_digest
                != digest_json(problem.informal_statement)
            )
        ):
            raise ValueError(f"mapping evidence does not match task {problem.task_id}")
        if (
            self.check is not None
            and self.check.environment_digest != environment_digest
        ):
            raise ValueError(f"stale mapping environment for task {problem.task_id}")


class MappingBundle(Record):
    """Public mapping evidence accompanying a manifest."""

    mappings: tuple[MappingEvidence, ...]

    @model_validator(mode="after")
    def _unique_mappings(self) -> Self:
        if len({item.evidence_id for item in self.mappings}) != len(
            self.mappings
        ) or len({item.task_id for item in self.mappings}) != len(self.mappings):
            raise ValueError("duplicate mapping evidence")
        return self


StatementChecker = Callable[[Problem, ReferenceType], StatementCheck]


def validate_mapping(
    problem: Problem,
    statement_checker: StatementChecker,
    *,
    evidence: MappingEvidence,
    environment_digest: str,
) -> MappingEvidence:
    """Refresh elaboration evidence without granting mathematical review status."""
    evidence.bind(problem, environment_digest)
    checked = statement_checker(problem, evidence.reference_type)
    status = evidence.status
    reason = evidence.status_reason
    if status == "curated_validated" and checked.result != "definitionally_equal":
        status = "needs_review"
        reason = checked.detail
    updated = MappingEvidence.model_validate(
        evidence.model_dump()
        | {"status": status, "status_reason": reason, "check": checked}
    )
    updated.bind(problem, environment_digest)
    return updated
