"""Validated configuration shared by training and evaluation."""

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    seed: int = 7
    episodes: int = 40
    chain_length: int = 7
    max_steps: int = 12
    hidden_dim: int = 32
    gamma: float = 0.95
    learning_rate: float = 0.01
    batch_size: int = 16
    replay_capacity: int = 2000
    target_update_interval: int = 20
    epsilon_start: float = 0.8
    epsilon_end: float = 0.1
    retrieval_enabled: bool = True
    retrieval_weight: float = 0.5
    retrieval_capacity: int = 2000
    retrieval_k: int = 3
    retrieval_max_distance: float = 0.01

    def __post_init__(self) -> None:
        for name in (
            "seed",
            "episodes",
            "chain_length",
            "max_steps",
            "hidden_dim",
            "batch_size",
            "replay_capacity",
            "target_update_interval",
            "retrieval_capacity",
            "retrieval_k",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < (0 if name == "seed" else 1):
                raise ValueError(
                    f"{name} must be a valid positive integer (seed may be zero)"
                )
        if self.chain_length < 3:
            raise ValueError("chain_length must be >= 3")
        if self.batch_size > self.replay_capacity:
            raise ValueError("batch_size exceeds replay_capacity")
        for name in ("gamma", "epsilon_start", "epsilon_end", "retrieval_weight"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be finite in [0, 1]")
        if not math.isfinite(self.learning_rate) or self.learning_rate <= 0:
            raise ValueError("learning_rate must be finite and positive")
        if (
            not math.isfinite(self.retrieval_max_distance)
            or self.retrieval_max_distance < 0
        ):
            raise ValueError("retrieval_max_distance must be finite and nonnegative")
        if type(self.retrieval_enabled) is not bool:
            raise ValueError("retrieval_enabled must be boolean")

    def to_dict(self) -> dict[str, int | float | bool]:
        return asdict(self)

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        return cls(**json.loads(Path(path).read_text(encoding="utf-8-sig")))
