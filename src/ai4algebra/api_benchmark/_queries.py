"""Versioned, bounded inputs for the retrieval benchmark."""

import re
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing_extensions import Self

from ai4algebra.api_benchmark._settings import BenchmarkConfigError
from ai4algebra.contracts import Identifier, Record

Service = Literal["stacks", "leanexplore", "loogle"]
SERVICES: tuple[Service, ...] = ("stacks", "leanexplore", "loogle")
_MAX_FILE_BYTES = 8 * 1024 * 1024


def valid_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 500
        and value == value.strip()
        and value.isprintable()
    )


class Query(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, hide_input_in_errors=True
    )

    id: Annotated[Identifier, StringConstraints(max_length=128)]
    service: Service
    query: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    expected_names: Annotated[tuple[str, ...], Field(max_length=100)] = ()
    category: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = (
        None
    )

    @model_validator(mode="after")
    def _validate_query(self) -> Self:
        if not self.query.strip() or any(
            not char.isprintable() and char not in "\t\r\n" for char in self.query
        ):
            raise ValueError("query must be nonblank text")
        if self.service == "stacks" and not re.fullmatch(r"[0-9A-Z]{4}", self.query):
            raise ValueError(
                "Stacks queries must be four-character uppercase alphanumeric tags"
            )
        if self.service == "stacks" and self.expected_names:
            raise ValueError("Stacks statement lookups do not have ranked names")
        if self.category is not None and (
            not self.category.strip() or not self.category.isprintable()
        ):
            raise ValueError("category must be nonblank text")
        if any(not valid_name(name) for name in self.expected_names):
            raise ValueError("expected names must be nonblank printable strings")
        if len(set(self.expected_names)) != len(self.expected_names):
            raise ValueError("expected names must be unique")
        return self


class QuerySet(Record):
    model_config = ConfigDict(hide_input_in_errors=True)

    queries: Annotated[tuple[Query, ...], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        if len({query.id for query in self.queries}) != len(self.queries):
            raise ValueError("query IDs must be unique")
        return self


def load_queries(path: Path) -> tuple[QuerySet, str]:
    try:
        with path.open("rb") as source:
            content = source.read(_MAX_FILE_BYTES + 1)
        if len(content) > _MAX_FILE_BYTES:
            raise BenchmarkConfigError("benchmark query file is too large")
        queries = QuerySet.from_json(content.decode("utf-8-sig"))
    except BenchmarkConfigError:
        raise
    except (OSError, ValueError, RecursionError):
        raise BenchmarkConfigError(
            "could not read a valid version 1 benchmark query file"
        ) from None
    return queries, sha256(content).hexdigest()
