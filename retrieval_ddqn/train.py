"""Train the experimental chain baseline: python -m retrieval_ddqn.train."""

import argparse
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TypedDict

import numpy as np

from .config import Config
from .contracts import Transition
from .environment import ChainEnv
from .learner import DoubleDQNLearner
from .policy import select_action
from .replay import ReplayBuffer
from .retrieval import RetrievalIndex, RetrievalRecord


class TrainMetrics(TypedDict):
    seed: int
    episodes: int
    steps: int
    retrieval_enabled: bool
    retrieval_hits: int
    memory_size: int
    updates: int
    mean_return: float
    success_rate: float
    mean_loss: float | None


def make_learner(config: Config) -> DoubleDQNLearner:
    return DoubleDQNLearner(
        config.chain_length,
        2,
        config.hidden_dim,
        config.seed,
        config.gamma,
        config.learning_rate,
        config.target_update_interval,
        tau=config.tau,
    )


def index_completed_episode(
    index: RetrievalIndex, transitions: Sequence[Transition], gamma: float
) -> None:
    """Publish returns after a completed training episode is observed."""
    if not transitions:
        return
    if any(t.split != "train" for t in transitions):
        raise ValueError("cannot publish held-out experience")
    if any(t.episode_id != transitions[0].episode_id for t in transitions):
        raise ValueError("cannot mix episodes")
    if any(t.terminated or t.truncated for t in transitions[:-1]):
        raise ValueError("episode contains transitions after completion")
    if any(b.step != a.step + 1 for a, b in zip(transitions, transitions[1:])):
        raise ValueError("episode steps must be contiguous")
    if not transitions[-1].terminated or transitions[-1].truncated:
        return  # Never use incomplete or time-limit-censored returns.
    value = 0.0
    records = []
    for transition in reversed(transitions):
        value = transition.reward + gamma * value
        records.append(
            RetrievalRecord(
                transition.state,
                transition.action,
                value,
                transition.step,
                transitions[-1].step,
                transition.episode_id,
            )
        )
    # Validate the entire batch before changing or evicting real memory.
    staging = RetrievalIndex(len(records), index.state_dim, index.action_count)
    for record in records:
        staging.add(record)
    for record in reversed(records):
        index.add(record)


def train(config: Config, output: str | Path) -> TrainMetrics:
    env = ChainEnv(config.chain_length, config.max_steps, config.seed)
    learner = make_learner(config)
    replay = ReplayBuffer(config.replay_capacity, config.seed + 1)
    index = RetrievalIndex(config.retrieval_capacity, config.chain_length, 2)
    rng = np.random.default_rng(config.seed + 2)
    global_step = 0
    hits = 0
    returns = []
    losses = []
    successes = 0
    for episode in range(config.episodes):
        state = env.reset()
        episode_id = f"train-{episode}"
        trajectory = []
        episode_return = 0.0
        fraction = episode / max(1, config.episodes - 1)
        epsilon = config.epsilon_start + fraction * (
            config.epsilon_end - config.epsilon_start
        )
        while True:
            action, matched = select_action(
                learner.online,
                index,
                state,
                config=config,
                before_step=global_step,
                episode_id=episode_id,
                epsilon=epsilon,
                rng=rng,
            )
            hits += int(matched)
            next_state, reward, terminated, truncated = env.step(action)
            transition = Transition(
                state,
                action,
                reward,
                next_state,
                terminated,
                truncated,
                global_step,
                episode_id,
            )
            replay.add(transition)
            trajectory.append(transition)
            global_step += 1
            episode_return += reward
            if len(replay) >= config.batch_size:
                losses.append(learner.update(replay.sample(config.batch_size))["loss"])
            state = next_state
            if terminated or truncated:
                successes += int(terminated)
                break
        if config.retrieval_enabled:
            index_completed_episode(index, trajectory, config.gamma)
        returns.append(episode_return)
    metrics: TrainMetrics = {
        "seed": config.seed,
        "episodes": config.episodes,
        "steps": global_step,
        "retrieval_enabled": config.retrieval_enabled,
        "retrieval_hits": hits,
        "memory_size": len(index),
        "updates": learner.update_steps,
        "mean_return": float(np.mean(returns)),
        "success_rate": successes / config.episodes,
        "mean_loss": float(np.mean(losses)) if losses else None,
    }
    checkpoint = {
        "version": 1,
        "config": config.to_dict(),
        "global_step": global_step,
        "learner": learner.state_dict(),
        "retrieval_records": index.to_records(),
    }
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "checkpoint.json").write_text(
        json.dumps(checkpoint, indent=2, allow_nan=False), encoding="utf-8"
    )
    (output / "train_metrics.json").write_text(
        json.dumps(metrics, indent=2, allow_nan=False), encoding="utf-8"
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/smoke.json")
    parser.add_argument("--output", required=True)
    parser.add_argument("--disable-retrieval", action="store_true")
    args = parser.parse_args()
    config = Config.load(args.config)
    if args.disable_retrieval:
        config = replace(config, retrieval_enabled=False)
    print(json.dumps(train(config, args.output), sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
