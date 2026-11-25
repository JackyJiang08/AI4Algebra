"""Bounded memory of completed training returns for causal action retrieval."""

from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from math import dist, isfinite
from numbers import Integral, Real
from statistics import mean
from typing import Any, TypedDict, cast


class RetrievalRecordData(TypedDict):
    state: list[float]
    action: int
    discounted_return: float
    transition_step: int
    available_at: int
    episode_id: str
    split: str


@dataclass(frozen=True)
class RetrievalRecord:
    state: tuple[float, ...]
    action: int
    discounted_return: float
    transition_step: int
    available_at: int
    episode_id: str
    split: str = "train"


def _integer(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


class RetrievalIndex:
    """FIFO training memory with nearest neighbors selected separately per action."""

    def __init__(self, capacity: int, state_dim: int, action_count: int) -> None:
        self.capacity = _integer(capacity, "capacity", 1)
        self.state_dim = _integer(state_dim, "state_dim", 1)
        self.action_count = _integer(action_count, "action_count", 1)
        self._records: deque[RetrievalRecord] = deque(maxlen=self.capacity)

    def __len__(self) -> int:
        return len(self._records)

    def _state(self, state: Iterable[object]) -> tuple[float, ...]:
        if isinstance(state, (str, bytes, Mapping, Set)):
            raise ValueError("state must be an ordered numeric vector")
        try:
            coordinates = tuple(state)
        except TypeError as exc:
            raise ValueError("state must be a vector") from exc
        if len(coordinates) != self.state_dim:
            raise ValueError(f"state must have {self.state_dim} coordinates")
        return tuple(_finite(value, "state coordinate") for value in coordinates)

    def add(self, record: RetrievalRecord) -> None:
        if not isinstance(record, RetrievalRecord) or record.split != "train":
            raise ValueError("only training retrieval records may be inserted")
        if not isinstance(record.episode_id, str) or not record.episode_id.strip():
            raise ValueError("episode_id must be a nonempty string")
        action = _integer(record.action, "action", 0)
        if action >= self.action_count:
            raise ValueError("action outside action space")
        step = _integer(record.transition_step, "transition_step", 0)
        available_at = _integer(record.available_at, "available_at", step)
        self._records.append(
            RetrievalRecord(
                state=self._state(record.state),
                action=action,
                discounted_return=_finite(
                    record.discounted_return, "discounted_return"
                ),
                transition_step=step,
                available_at=available_at,
                episode_id=record.episode_id,
            )
        )

    def query(
        self,
        state: Iterable[object],
        *,
        before_step: int,
        exclude_episode_id: str | None = None,
        k: int = 3,
        max_distance: float = 0.01,
    ) -> dict[int, float]:
        state = self._state(state)
        before_step = _integer(before_step, "before_step", 0)
        k = _integer(k, "k", 1)
        max_distance = _finite(max_distance, "max_distance")
        if max_distance < 0:
            raise ValueError("max_distance must be nonnegative")
        matches: dict[int, list[tuple[float, float]]] = defaultdict(list)
        for record in self._records:
            if (
                record.transition_step >= before_step
                or record.available_at >= before_step
                or record.episode_id == exclude_episode_id
            ):
                continue
            distance = dist(state, record.state)
            if distance <= max_distance:
                matches[record.action].append((distance, record.discounted_return))

        scores = {}
        for action, neighbors in matches.items():
            # Python's stable sort retains FIFO insertion order at equal distances.
            neighbors.sort(key=lambda pair: pair[0])
            scores[action] = mean(value for _, value in neighbors[:k])
        return scores

    def to_records(self) -> list[RetrievalRecordData]:
        return [
            {
                "state": list(record.state),
                "action": record.action,
                "discounted_return": record.discounted_return,
                "transition_step": record.transition_step,
                "available_at": record.available_at,
                "episode_id": record.episode_id,
                "split": record.split,
            }
            for record in self._records
        ]

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, object]],
        *,
        capacity: int,
        state_dim: int,
        action_count: int,
    ) -> "RetrievalIndex":
        if isinstance(records, (Mapping, str, bytes)) or not isinstance(
            records, Iterable
        ):
            raise ValueError("serialized index must be a sequence of records")
        index = cls(capacity, state_dim, action_count)
        for fields in records:
            if len(index) >= capacity:
                raise ValueError("serialized index exceeds capacity")
            try:
                # The constructor checks the field names and add validates their values.
                record = RetrievalRecord(**cast(Mapping[str, Any], fields))
            except TypeError as exc:
                raise ValueError("invalid retrieval record fields") from exc
            index.add(record)
        return index
