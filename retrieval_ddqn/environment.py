"""Synthetic chain task, deliberately independent of Lean proof verification."""

import numpy as np


class ChainEnv:
    action_count = 2  # left, right

    def __init__(self, length: int = 7, max_steps: int = 12, seed: int = 0) -> None:
        if length < 3 or max_steps < 1:
            raise ValueError("invalid environment dimensions")
        self.length = length
        self.max_steps = max_steps
        self.rng = np.random.default_rng(seed)
        self.done = True

    def observation(self) -> tuple[float, ...]:
        return tuple(float(i == self.position) for i in range(self.length))

    def reset(self) -> tuple[float, ...]:
        self.position = int(self.rng.integers(0, self.length - 1))
        self.steps = 0
        self.done = False
        return self.observation()

    def step(self, action: int) -> tuple[tuple[float, ...], float, bool, bool]:
        if self.done:
            raise RuntimeError("reset before stepping a completed episode")
        if action not in (0, 1):
            raise ValueError("action must be 0 or 1")
        self.position = min(
            self.length - 1, max(0, self.position + (1 if action else -1))
        )
        self.steps += 1
        terminated = self.position == self.length - 1
        truncated = self.steps >= self.max_steps and not terminated
        self.done = terminated or truncated
        reward = 1.0 if terminated else -0.01
        return self.observation(), reward, terminated, truncated
