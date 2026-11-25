"""Uniform, bounded training-only replay."""

from collections import deque

import numpy as np

from .contracts import Transition


class ReplayBuffer:
    def __init__(self, capacity: int, seed: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.items: deque[Transition] = deque(maxlen=capacity)
        self.rng = np.random.default_rng(seed)

    def add(self, transition: Transition) -> None:
        if transition.split != "train":
            raise ValueError("replay accepts only training transitions")
        self.items.append(transition)

    def sample(self, size: int) -> list[Transition]:
        if not 1 <= size <= len(self.items):
            raise ValueError("sample size exceeds available replay or is nonpositive")
        return [
            self.items[int(i)]
            for i in self.rng.choice(len(self.items), size, replace=False)
        ]

    def __len__(self) -> int:
        return len(self.items)
