import json
from dataclasses import replace
from functools import partial
from typing import Any, TypedDict

import pytest

from retrieval_ddqn.retrieval import (
    RetrievalIndex,
    RetrievalRecord,
    RetrievalRecordData,
)

RECORD = RetrievalRecord((0.0, 0.0), 0, 4.0, 2, 3, "train-a")


def test_query_filters_before_ranking_and_waits_for_completed_returns() -> None:
    index = RetrievalIndex(10, 2, 2)
    query = partial(
        index.query, before_step=8, exclude_episode_id="current", k=1, max_distance=0.5
    )
    assert query((0, 0)) == {}
    for record in (
        replace(RECORD, episode_id="current"),
        replace(RECORD, available_at=8),
        replace(RECORD, transition_step=9, available_at=10),
        replace(RECORD, state=(0.4, 0.4)),  # Outside Euclidean radius.
    ):
        index.add(record)
    assert query((0, 0)) == {}
    index.add(replace(RECORD, state=(0.3, 0.4), discounted_return=7))
    assert query((0, 0)) == {0: 7}


def test_nearest_k_per_action_and_insertion_order_for_ties() -> None:
    index = RetrievalIndex(10, 2, 2)
    for x, action, value in [
        (0.4, 0, 20),
        (0.2, 0, 3),
        (-0.2, 0, 10),
        (0, 0, 1),
        (0.4, 1, -1),
        (0.3, 1, -7),
    ]:
        index.add(replace(RECORD, state=(x, 0), action=action, discounted_return=value))
    assert index.query((0, 0), before_step=4, k=2, max_distance=0.5) == {0: 2, 1: -4}


def test_checkpoint_round_trip_preserves_cutoff_and_fifo_order() -> None:
    index = RetrievalIndex(2, 2, 2)
    for value in (10, 11, 12):
        index.add(replace(RECORD, discounted_return=value))
    data: list[RetrievalRecordData] = json.loads(
        json.dumps(index.to_records(), allow_nan=False)
    )
    restored = RetrievalIndex.from_records(
        data, capacity=2, state_dim=2, action_count=2
    )
    data[0]["state"][0] = 999
    assert restored.to_records() == index.to_records()
    assert len(restored) == 2
    assert restored.query((0, 0), before_step=3) == {}
    assert restored.query((0, 0), before_step=4, k=1) == {0: 11}
    restored.add(RECORD)
    assert restored.query((0, 0), before_step=4, k=1) == {0: 12}


@pytest.mark.parametrize(
    "changes",
    [
        {"split": "eval"},
        {"state": (1,)},
        {"state": (float("nan"), 0)},
        {"discounted_return": float("inf")},
        {"action": -1},
        {"action": 2},
        {"action": True},
        {"transition_step": -1},
        {"available_at": 1},
        {"transition_step": 1.5},
        {"episode_id": ""},
    ],
)
def test_invalid_insertion_and_checkpoint_rejected(changes: dict[str, Any]) -> None:
    index = RetrievalIndex(1, 2, 2)
    index.add(RECORD)
    with pytest.raises(ValueError):
        # These cases deliberately bypass the dataclass field types.
        index.add(replace(RECORD, **changes))
    assert index.query((0, 0), before_step=4) == {0: 4}
    fields = {**index.to_records()[0], **changes}
    with pytest.raises(ValueError):
        RetrievalIndex.from_records([fields], capacity=1, state_dim=2, action_count=2)


def test_checkpoint_invalid_fields_and_excess_records_rejected() -> None:
    index = RetrievalIndex(1, 2, 2)
    index.add(RECORD)
    empty_fields: dict[str, object] = {}
    for data in ([empty_fields], index.to_records() * 2):
        with pytest.raises(ValueError):
            RetrievalIndex.from_records(data, capacity=1, state_dim=2, action_count=2)


class QueryOptions(TypedDict, total=False):
    before_step: int
    k: int
    max_distance: float


@pytest.mark.parametrize(
    "options",
    [
        {"before_step": -1},
        {"k": 0},
        {"max_distance": -1},
        {"max_distance": float("nan")},
    ],
)
def test_invalid_query_rejected_even_if_empty(options: QueryOptions) -> None:
    index = RetrievalIndex(1, 2, 2)
    with pytest.raises(ValueError):
        query_options: QueryOptions = {"before_step": 0, **options}
        index.query((0, 0), **query_options)
