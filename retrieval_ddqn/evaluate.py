"""Evaluate a frozen model and its training memory on independently seeded episodes."""

import argparse
import json
from pathlib import Path
from typing import TypedDict

import numpy as np

from .config import Config
from .environment import ChainEnv
from .learner import DoubleDQNLearner
from .policy import select_action
from .retrieval import RetrievalIndex
from .train import make_learner


class EvaluationMetrics(TypedDict):
    seed: int
    episodes: int
    steps: int
    retrieval_enabled: bool
    retrieval_hits: int
    memory_size: int
    checkpoint_step: int
    mean_return: float
    success_rate: float


def load_checkpoint(
    path: str | Path,
) -> tuple[Config, DoubleDQNLearner, RetrievalIndex, int]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("unsupported checkpoint version")
    config = Config(**data["config"])
    cutoff = data["global_step"]
    if type(cutoff) is not int or cutoff < 0:
        raise ValueError("invalid checkpoint global_step")
    learner = make_learner(config)
    learner.load_state_dict(data["learner"])
    index = RetrievalIndex.from_records(
        data["retrieval_records"],
        capacity=config.retrieval_capacity,
        state_dim=config.chain_length,
        action_count=2,
    )
    return config, learner, index, cutoff


def evaluate(
    checkpoint: str | Path, episodes: int = 10, seed: int = 101
) -> EvaluationMetrics:
    if type(episodes) is not int or episodes < 1 or type(seed) is not int or seed < 0:
        raise ValueError("episodes must be positive and seed nonnegative integers")
    config, learner, index, cutoff = load_checkpoint(checkpoint)
    env = ChainEnv(config.chain_length, config.max_steps, seed)
    rng = np.random.default_rng(seed + 1)
    returns = []
    successes = 0
    hits = 0
    steps = 0
    for episode in range(episodes):
        state = env.reset()
        total = 0.0
        while True:
            action, matched = select_action(
                learner.online,
                index,
                state,
                config=config,
                before_step=cutoff,
                episode_id=f"eval-{episode}",
                epsilon=0.0,
                rng=rng,
            )
            hits += int(matched)
            state, reward, terminated, truncated = env.step(action)
            total += reward
            steps += 1
            if terminated or truncated:
                successes += int(terminated)
                break
        returns.append(total)
    return {
        "seed": seed,
        "episodes": episodes,
        "steps": steps,
        "retrieval_enabled": config.retrieval_enabled,
        "retrieval_hits": hits,
        "memory_size": len(index),
        "checkpoint_step": cutoff,
        "mean_return": float(np.mean(returns)),
        "success_rate": successes / episodes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--episodes", type=int, default=10)
    parser.add_argument("--seed", type=int, default=101)
    args = parser.parse_args()
    print(
        json.dumps(
            evaluate(args.checkpoint, args.episodes, args.seed),
            sort_keys=True,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
