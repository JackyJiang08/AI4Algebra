"""A two-layer NumPy Q-network and its Double DQN update."""

from collections.abc import Mapping, Sequence
from typing import TypedDict, cast

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .contracts import Transition

FloatArray = NDArray[np.float64]
NetworkState = dict[str, list[float] | list[list[float]]]


class LearnerMetrics(TypedDict):
    loss: float
    target_mean: float
    update_steps: int


class LearnerState(TypedDict):
    online: NetworkState
    target: NetworkState
    update_steps: int


def _finite_array(values: ArrayLike, name: str) -> FloatArray:
    array = np.asarray(values, dtype=np.float64)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite values")
    return array


class MLP:
    def __init__(
        self, state_dim: int, action_count: int, hidden_dim: int, seed: int
    ) -> None:
        if min(state_dim, action_count, hidden_dim) < 1:
            raise ValueError("network dimensions must be positive")
        rng = np.random.default_rng(seed)
        self.w1: FloatArray = rng.normal(
            0, np.sqrt(2 / state_dim), (state_dim, hidden_dim)
        )
        self.b1: FloatArray = np.zeros(hidden_dim)
        self.w2: FloatArray = rng.normal(
            0, np.sqrt(1 / hidden_dim), (hidden_dim, action_count)
        )
        self.b2: FloatArray = np.zeros(action_count)

    def _forward(self, states: ArrayLike) -> tuple[FloatArray, FloatArray, FloatArray]:
        x = _finite_array(states, "states")
        if x.ndim == 1:
            x = x[None, :]
        if x.ndim != 2 or x.shape[1] != self.w1.shape[0]:
            raise ValueError("states must have shape (batch, state_dim)")
        hidden = np.maximum(0.0, x @ self.w1 + self.b1)
        return x, hidden, hidden @ self.w2 + self.b2

    def predict(self, states: ArrayLike) -> FloatArray:
        return self._forward(states)[2]

    def train(
        self,
        states: ArrayLike,
        actions: ArrayLike,
        targets: ArrayLike,
        learning_rate: float,
    ) -> float:
        x, hidden, predictions = self._forward(states)
        batch, action_count = predictions.shape
        actions = np.asarray(actions)
        targets = _finite_array(targets, "targets")
        if batch == 0 or actions.shape != (batch,) or targets.shape != (batch,):
            raise ValueError("train needs one action and target for each sample")
        if actions.dtype.kind not in "iu" or np.any(
            (actions < 0) | (actions >= action_count)
        ):
            raise ValueError("action index out of range or non-integral")
        if not np.isfinite(learning_rate) or learning_rate <= 0:
            raise ValueError("learning_rate must be finite and positive")

        rows = np.arange(batch)
        errors = predictions[rows, actions] - targets
        grad_q = np.zeros_like(predictions)
        grad_q[rows, actions] = (2.0 / batch) * errors
        grad_hidden = (grad_q @ self.w2.T) * (hidden > 0)
        self.w1 -= learning_rate * (x.T @ grad_hidden)
        self.b1 -= learning_rate * grad_hidden.sum(axis=0)
        self.w2 -= learning_rate * (hidden.T @ grad_q)
        self.b2 -= learning_rate * grad_q.sum(axis=0)
        return float(np.mean(errors**2))

    def _parameters(self) -> dict[str, FloatArray]:
        return {"w1": self.w1, "b1": self.b1, "w2": self.w2, "b2": self.b2}

    def copy_from(self, other: "MLP") -> None:
        self.load_state_dict(other._parameters())

    def state_dict(self) -> NetworkState:
        return {
            name: cast(list[float] | list[list[float]], value.tolist())
            for name, value in self._parameters().items()
        }

    def _validated_parameters(self, data: object) -> dict[str, FloatArray]:
        params = self._parameters()
        if not isinstance(data, dict) or data.keys() != params.keys():
            raise ValueError("checkpoint network parameters do not match")
        arrays = {name: _finite_array(data[name], name) for name in params}
        if any(arrays[name].shape != params[name].shape for name in params):
            raise ValueError("checkpoint network dimensions do not match")
        return arrays

    def load_state_dict(self, data: object) -> None:
        self._set_parameters(self._validated_parameters(data))

    def _set_parameters(self, parameters: Mapping[str, FloatArray]) -> None:
        for name, value in parameters.items():
            np.copyto(getattr(self, name), value)


def double_dqn_targets(
    rewards: ArrayLike,
    terminated: ArrayLike,
    next_online_q: ArrayLike,
    next_target_q: ArrayLike,
    gamma: float,
) -> FloatArray:
    """Select with the online network and bootstrap with the target network."""
    online = _finite_array(next_online_q, "next_online_q")
    target = _finite_array(next_target_q, "next_target_q")
    rewards = _finite_array(rewards, "rewards")
    terminated = np.asarray(terminated)
    if online.ndim != 2 or online.shape != target.shape or online.shape[1] == 0:
        raise ValueError("next Q arrays must have the same (batch, action_count) shape")
    if rewards.shape != (len(online),) or terminated.shape != rewards.shape:
        raise ValueError("batch dimensions must agree")
    if not np.all(np.isin(terminated, [False, True])):
        raise ValueError("terminated must contain boolean flags")
    if not 0 <= gamma <= 1:
        raise ValueError("gamma must be between zero and one")
    chosen = online.argmax(axis=1)
    bootstrap = target[np.arange(len(chosen)), chosen]
    targets: FloatArray = rewards + gamma * np.where(terminated, 0.0, bootstrap)
    return targets


class DoubleDQNLearner:
    def __init__(
        self,
        state_dim: int,
        action_count: int,
        hidden_dim: int,
        seed: int,
        gamma: float,
        learning_rate: float,
        target_update_interval: int,
    ) -> None:
        if not 0 <= gamma <= 1:
            raise ValueError("gamma must be between zero and one")
        if not np.isfinite(learning_rate) or learning_rate <= 0:
            raise ValueError("learning_rate must be finite and positive")
        if type(target_update_interval) is not int or target_update_interval < 1:
            raise ValueError("target_update_interval must be a positive integer")
        self.online = MLP(state_dim, action_count, hidden_dim, seed)
        self.target = MLP(state_dim, action_count, hidden_dim, seed)
        self.target.copy_from(self.online)
        self.gamma = gamma
        self.learning_rate = learning_rate
        self.target_update_interval = target_update_interval
        self.update_steps = 0

    def update(self, transitions: Sequence[Transition]) -> LearnerMetrics:
        if len(transitions) == 0 or any(t.split != "train" for t in transitions):
            raise ValueError("update requires a nonempty batch of training transitions")
        next_states = [t.next_state for t in transitions]
        targets = double_dqn_targets(
            [t.reward for t in transitions],
            [t.terminated for t in transitions],
            self.online.predict(next_states),
            self.target.predict(next_states),
            self.gamma,
        )
        loss = self.online.train(
            [t.state for t in transitions],
            [t.action for t in transitions],
            targets,
            self.learning_rate,
        )
        self.update_steps += 1
        if self.update_steps % self.target_update_interval == 0:
            self.target.copy_from(self.online)
        return {
            "loss": loss,
            "target_mean": float(targets.mean()),
            "update_steps": self.update_steps,
        }

    def state_dict(self) -> LearnerState:
        return {
            "online": self.online.state_dict(),
            "target": self.target.state_dict(),
            "update_steps": self.update_steps,
        }

    def load_state_dict(self, data: Mapping[str, object]) -> None:
        steps = data["update_steps"]
        if type(steps) is not int or steps < 0:
            raise ValueError("update_steps must be a nonnegative integer")
        online = self.online._validated_parameters(data["online"])
        target = self.target._validated_parameters(data["target"])
        self.online._set_parameters(online)
        self.target._set_parameters(target)
        self.update_steps = steps
