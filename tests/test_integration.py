import json
from dataclasses import replace
from pathlib import Path
from typing import NoReturn, TypedDict

import numpy as np
import pytest

from retrieval_ddqn.config import Config
from retrieval_ddqn.contracts import Transition
from retrieval_ddqn.environment import ChainEnv
from retrieval_ddqn.evaluate import evaluate, load_checkpoint
from retrieval_ddqn.learner import FloatArray
from retrieval_ddqn.policy import guided_scores, select_action
from retrieval_ddqn.replay import ReplayBuffer
from retrieval_ddqn.retrieval import RetrievalIndex, RetrievalRecord
from retrieval_ddqn.train import index_completed_episode, train


class FixedNetwork:
    def predict(self, states: FloatArray) -> FloatArray:
        return np.tile([0.4, 0.2], (len(states), 1))


def choose(
    index: RetrievalIndex,
    cutoff: int = 5,
    enabled: bool = True,
    episode: str = "current",
) -> tuple[int, bool]:
    return select_action(
        FixedNetwork(),
        index,
        (1.0, 0.0, 0.0),
        config=Config(chain_length=3, retrieval_enabled=enabled),
        before_step=cutoff,
        episode_id=episode,
        epsilon=0.0,
        rng=np.random.default_rng(1),
    )


def test_known_retrieval_changes_action_and_causal_fallback() -> None:
    index = RetrievalIndex(10, 3, 2)
    assert choose(index) == (0, False)
    index.add(RetrievalRecord((1.0, 0.0, 0.0), 1, 1.0, 1, 4, "past"))
    np.testing.assert_allclose(guided_scores([0.4, 0.2], {1: 1.0}, 0.5), [0.4, 0.6])
    assert choose(index) == (1, True)
    assert choose(index, cutoff=4) == (0, False)  # Return not yet available.
    assert choose(index, enabled=False) == (0, False)
    assert choose(index, episode="past") == (0, False)
    index.add(RetrievalRecord((1.0, 0.0, 0.0), 0, 100.0, 50, 50, "future"))
    assert choose(index) == (1, True)
    with pytest.raises(ValueError):
        index.add(RetrievalRecord((1.0, 0.0, 0.0), 0, 100.0, 1, 1, "held-out", "eval"))


def trajectory(terminated: bool = True, split: str = "train") -> list[Transition]:
    return [
        Transition(
            (1.0, 0.0, 0.0),
            1,
            -0.01,
            (0.0, 1.0, 0.0),
            False,
            False,
            0,
            "train-0",
            split,
        ),
        Transition(
            (0.0, 1.0, 0.0),
            1,
            1.0,
            (0.0, 0.0, 1.0),
            terminated,
            not terminated,
            1,
            "train-0",
            split,
        ),
    ]


def test_publish_returns_only_after_completed_training_episode() -> None:
    index = RetrievalIndex(10, 3, 2)
    index_completed_episode(index, trajectory()[:1], 0.9)
    index_completed_episode(index, trajectory(terminated=False), 0.9)
    assert len(index) == 0
    with pytest.raises(ValueError):
        index_completed_episode(index, trajectory(split="eval"), 0.9)
    index_completed_episode(index, trajectory(), 0.9)
    assert index.query((1.0, 0.0, 0.0), before_step=1) == {}
    assert index.query((1.0, 0.0, 0.0), before_step=2) == {1: pytest.approx(0.89)}
    assert {r["available_at"] for r in index.to_records()} == {1}


@pytest.mark.parametrize("terminated", [False, True])
def test_truncated_episode_never_enters_return_memory(terminated: bool) -> None:
    index = RetrievalIndex(1, 3, 2)
    index.add(RetrievalRecord((1.0, 0.0, 0.0), 0, 0.5, 0, 0, "old"))
    before = index.to_records()
    transitions = trajectory()
    transitions[-1] = replace(transitions[-1], terminated=terminated, truncated=True)
    index_completed_episode(index, transitions, 0.9)
    assert index.to_records() == before


def test_environment_exposes_final_observation_at_time_limit() -> None:
    env = ChainEnv(3, 1, 7)
    env.reset()
    env.position = 1
    state, reward, terminated, truncated = env.step(0)
    assert state == (1.0, 0.0, 0.0)
    assert not terminated and truncated
    assert reward == -0.01
    with pytest.raises(RuntimeError):
        env.step(1)
    env.reset()
    env.position = 1
    assert env.step(1)[2:] == (True, False)  # Success at horizon is terminal.


def test_replay_capacity_sampling_and_split() -> None:
    replay = ReplayBuffer(1, 0)
    first, last = trajectory()
    replay.add(first)
    replay.add(last)
    assert replay.sample(1) == [last]
    with pytest.raises(ValueError):
        replay.add(replace(last, split="eval"))
    with pytest.raises(ValueError):
        replay.sample(2)


@pytest.mark.parametrize("enabled", [True, False])
def test_seeded_workflow_and_frozen_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    config = Config(
        episodes=12,
        chain_length=3,
        max_steps=6,
        batch_size=4,
        retrieval_enabled=enabled,
    )
    first = train(config, tmp_path / "first")
    second = train(config, tmp_path / "second")
    assert first == second
    path = tmp_path / "first" / "checkpoint.json"
    checkpoint_bytes = path.read_bytes()
    assert checkpoint_bytes == (tmp_path / "second" / "checkpoint.json").read_bytes()
    cfg, learner, index, cutoff = load_checkpoint(path)
    assert learner.update_steps > 0
    assert all(
        r["available_at"] < cutoff and r["split"] == "train" for r in index.to_records()
    )
    if enabled:
        assert first["memory_size"] > 0 and first["retrieval_hits"] > 0
    else:
        assert first["memory_size"] == first["retrieval_hits"] == 0

    # Forbid evaluation writes even to in-memory model/index/replay, not only disk.
    import retrieval_ddqn.evaluate as eval_module

    monkeypatch.setattr(
        eval_module, "load_checkpoint", lambda _: (cfg, learner, index, cutoff)
    )

    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("evaluation must not learn or insert experience")

    monkeypatch.setattr(index, "add", forbidden)
    monkeypatch.setattr(learner, "update", forbidden)
    monkeypatch.setattr(learner.online, "train", forbidden)
    monkeypatch.setattr(ReplayBuffer, "add", forbidden)
    before = json.dumps({"learner": learner.state_dict(), "index": index.to_records()})
    metrics = evaluate(path, episodes=5, seed=101)
    assert metrics == evaluate(path, episodes=5, seed=101)
    assert before == json.dumps(
        {"learner": learner.state_dict(), "index": index.to_records()}
    )
    assert checkpoint_bytes == path.read_bytes()


class ConfigOverrides(TypedDict, total=False):
    gamma: float
    batch_size: int
    episodes: int
    retrieval_max_distance: float


@pytest.mark.parametrize(
    "kwargs",
    [
        {"gamma": 1.1},
        {"batch_size": 3000},
        {"episodes": 0},
        {"retrieval_max_distance": float("nan")},
    ],
)
def test_configuration_rejects_invalid_values(kwargs: ConfigOverrides) -> None:
    with pytest.raises(ValueError):
        Config(**kwargs)


def test_malformed_completed_episode_cannot_partially_evict_memory() -> None:
    index = RetrievalIndex(1, 3, 2)
    index.add(RetrievalRecord((1.0, 0.0, 0.0), 0, 0.5, 0, 0, "old"))
    before = index.to_records()
    malformed = trajectory()
    malformed[-1] = replace(malformed[-1], state=(0.0, 1.0))
    with pytest.raises(ValueError, match="coordinates"):
        index_completed_episode(index, malformed, 0.9)
    assert index.to_records() == before
