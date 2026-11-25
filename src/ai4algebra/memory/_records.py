"""Shared provenance checks for persisted training memory."""

from collections.abc import Mapping
from typing import Annotated

from pydantic import Field, ValidationInfo, model_validator
from typing_extensions import Self

from ai4algebra.contracts import (
    Digest,
    Identifier,
    Problem,
    Record,
    Transition,
    digest_json,
)

PositiveInt = Annotated[int, Field(ge=1)]
NonnegativeInt = Annotated[int, Field(ge=0)]


def nonnegative_int(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def training_problem(task_id: str, task_sources: Mapping[str, Problem]) -> Problem:
    problem = task_sources.get(task_id)
    if problem is None or problem.task_id != task_id or problem.split != "train":
        raise ValueError("memory requires a task from the trusted training catalog")
    return problem


class TrainingTrace(Record):
    transition: Transition
    source_digest: Digest
    statement_digest: Digest

    @classmethod
    def capture(
        cls, transition: Transition, task_sources: Mapping[str, Problem]
    ) -> "TrainingTrace":
        if not isinstance(transition, Transition):
            raise ValueError("memory requires a Transition")
        validated = Transition.from_json(transition.to_json())
        problem = training_problem(validated.task_id, task_sources)
        return TrainingTrace(
            transition=validated,
            source_digest=problem.source.content_digest,
            statement_digest=problem.statement_digest,
        )

    def validate_source(self, task_sources: Mapping[str, Problem]) -> None:
        problem = training_problem(self.transition.task_id, task_sources)
        if (
            self.source_digest != problem.source.content_digest
            or self.statement_digest != problem.statement_digest
        ):
            raise ValueError("memory provenance differs from the trusted task catalog")


class MemorySettings(Record):
    capacity: PositiveInt
    run_id: Identifier


class MemoryArchive(Record):
    artifact_digest: Digest = Field(default="", validate_default=False)

    @model_validator(mode="after")
    def _validate_digest(self, info: ValidationInfo) -> Self:
        actual = digest_json(self.model_dump(mode="json", exclude={"artifact_digest"}))
        if info.mode == "json" and "artifact_digest" not in self.model_fields_set:
            raise ValueError("missing memory artifact digest")
        if self.artifact_digest and self.artifact_digest != actual:
            raise ValueError("memory artifact digest does not match")
        object.__setattr__(self, "artifact_digest", actual)
        return self
