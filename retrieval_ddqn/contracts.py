"""Shared immutable transition contract."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Transition:
    state: tuple[float, ...]
    action: int
    reward: float
    next_state: tuple[float, ...]
    terminated: bool
    truncated: bool
    step: int
    episode_id: str
    split: str = "train"
