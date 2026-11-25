"""Retrieval only modifies behavior scores; Bellman targets remain standard DDQN."""

from collections.abc import Mapping, Sequence
from typing import Protocol

import numpy as np
from numpy.typing import ArrayLike

from .config import Config
from .learner import FloatArray
from .retrieval import RetrievalIndex


class QNetwork(Protocol):
    def predict(self, states: FloatArray) -> FloatArray: ...


def guided_scores(
    q_values: ArrayLike, retrieved: Mapping[int, float], weight: float
) -> FloatArray:
    if not 0 <= weight <= 1:
        raise ValueError("retrieval weight must be in [0, 1]")
    scores = np.asarray(q_values, dtype=float).copy()
    if scores.ndim != 1 or not np.isfinite(scores).all():
        raise ValueError("Q values must be a finite action vector")
    for action, value in retrieved.items():
        if not 0 <= action < len(scores) or not np.isfinite(value):
            raise ValueError("invalid retrieved action/value")
        scores[action] = (1 - weight) * scores[action] + weight * value
    return scores


def select_action(
    online: QNetwork,
    index: RetrievalIndex,
    state: Sequence[float] | FloatArray,
    *,
    config: Config,
    before_step: int,
    episode_id: str,
    epsilon: float,
    rng: np.random.Generator,
) -> tuple[int, bool]:
    q_values = online.predict(np.asarray([state], dtype=float))[0]
    matches = (
        index.query(
            state,
            before_step=before_step,
            exclude_episode_id=episode_id,
            k=config.retrieval_k,
            max_distance=config.retrieval_max_distance,
        )
        if config.retrieval_enabled
        else {}
    )
    scores = guided_scores(q_values, matches, config.retrieval_weight)
    action = (
        int(rng.integers(len(scores)))
        if rng.random() < epsilon
        else int(np.argmax(scores))
    )
    return action, bool(matches)
