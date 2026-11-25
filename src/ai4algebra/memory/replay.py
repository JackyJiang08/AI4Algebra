"""Bounded FIFO replay with atomic inserts and read-only checkpoints."""

from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from threading import Lock

from numpy.random import Generator
from pydantic import model_validator
from typing_extensions import Self

from ai4algebra.contracts import Problem, Transition

from ._records import MemoryArchive, MemorySettings, TrainingTrace


class _ReplayArchive(MemoryArchive):
    settings: MemorySettings
    records: tuple[TrainingTrace, ...]

    @model_validator(mode="after")
    def _validate_capacity(self) -> Self:
        if len(self.records) > self.settings.capacity:
            raise ValueError("replay artifact exceeds capacity")
        return self


def _sample(
    records: Sequence[TrainingTrace], batch: int, rng: Generator
) -> list[Transition]:
    if type(batch) is not int or not 1 <= batch <= len(records):
        raise ValueError("batch must be a positive integer within replay size")
    indices = rng.choice(len(records), size=batch, replace=False)
    return [records[int(index)].transition for index in indices]


@dataclass(frozen=True, slots=True)
class FrozenReplay:
    """An immutable replay archive. Sampling uses caller-owned RNG state."""

    _archive: _ReplayArchive

    def __len__(self) -> int:
        return len(self._archive.records)

    @property
    def artifact_digest(self) -> str:
        return self._archive.artifact_digest

    def sample(self, batch: int, rng: Generator) -> list[Transition]:
        return _sample(self._archive.records, batch, rng)

    def to_json(self) -> str:
        return self._archive.to_json()

    @classmethod
    def from_json(
        cls, data: str | bytes, *, run_id: str, task_sources: Mapping[str, Problem]
    ) -> Self:
        archive = _ReplayArchive.from_json(data)
        if archive.settings.run_id != run_id:
            raise ValueError("replay run ID does not match")
        for item in archive.records:
            item.validate_source(task_sources)
        return cls(archive)


class Replay:
    def __init__(
        self, capacity: int, *, run_id: str, task_sources: Mapping[str, Problem]
    ) -> None:
        self._settings = MemorySettings(capacity=capacity, run_id=run_id)
        self._task_sources = dict(task_sources)
        self._records: deque[TrainingTrace] = deque(maxlen=capacity)
        self._lock = Lock()

    def __len__(self) -> int:
        return len(self._records)

    def add(self, transition: Transition) -> None:
        self.extend((transition,))

    def extend(self, transitions: Iterable[Transition]) -> None:
        staged = deque(
            (
                TrainingTrace.capture(transition, self._task_sources)
                for transition in transitions
            ),
            maxlen=self._settings.capacity,
        )
        with self._lock:
            self._records.extend(staged)

    def sample(self, batch: int, rng: Generator) -> list[Transition]:
        with self._lock:
            records = tuple(self._records)
        return _sample(records, batch, rng)

    def freeze(self) -> FrozenReplay:
        with self._lock:
            records = tuple(self._records)
        return FrozenReplay(_ReplayArchive(settings=self._settings, records=records))

    def to_json(self) -> str:
        return self.freeze().to_json()
