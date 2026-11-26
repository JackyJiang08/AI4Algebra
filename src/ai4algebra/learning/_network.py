"""A shared scalar NumPy network over concatenated state and candidate vectors."""

from dataclasses import dataclass
from math import isfinite
from typing import cast

import numpy as np
from numpy.typing import NDArray
from typing_extensions import Self

from ai4algebra.contracts import Record

FloatArray = NDArray[np.float64]


class NetworkParameters(Record):
    weights: tuple[tuple[float, ...], ...]
    bias: tuple[float, ...]
    readout: tuple[float, ...]
    offset: float


@dataclass
class ScalarQ:
    weights: FloatArray
    bias: FloatArray
    readout: FloatArray
    offset: float

    @classmethod
    def initialize(cls, input_size: int, hidden_size: int, seed: int) -> Self:
        rng = np.random.default_rng(seed)
        return cls(
            weights=rng.normal(
                0.0, np.sqrt(2.0 / input_size), (input_size, hidden_size)
            ),
            bias=np.zeros(hidden_size),
            readout=rng.normal(0.0, np.sqrt(1.0 / hidden_size), hidden_size),
            offset=0.0,
        )

    def copy(self) -> Self:
        return type(self)(
            self.weights.copy(), self.bias.copy(), self.readout.copy(), self.offset
        )

    def _forward(self, pairs: FloatArray) -> tuple[FloatArray, FloatArray]:
        with np.errstate(over="raise", invalid="raise"):
            hidden = np.maximum(
                0.0, np.einsum("bi,ih->bh", pairs, self.weights) + self.bias
            )
            scores = np.einsum("bh,h->b", hidden, self.readout) + self.offset
        if not np.isfinite(scores).all():
            raise FloatingPointError("network scores must remain finite")
        return hidden, scores

    def predict(self, pairs: FloatArray) -> FloatArray:
        return self._forward(pairs)[1]

    def train(
        self,
        pairs: FloatArray,
        targets: FloatArray,
        learning_rate: float,
        *,
        huber_delta: float | None = None,
    ) -> float:
        """Update only the supplied chosen pairs, with precomputed targets."""
        hidden, scores = self._forward(pairs)
        with np.errstate(over="raise", invalid="raise"):
            errors = scores - targets
            if huber_delta is None:
                loss = float(np.mean(errors**2))
                grad_q = (2.0 / len(pairs)) * errors
            else:
                absolute_errors = np.abs(errors)
                grad_q = np.clip(errors, -huber_delta, huber_delta)
                quadratic = np.abs(grad_q)
                loss = float(np.mean(quadratic * (absolute_errors - 0.5 * quadratic)))
                grad_q /= len(pairs)
            grad_hidden = grad_q[:, None] * self.readout * (hidden > 0.0)
            weights = self.weights - learning_rate * (pairs.T @ grad_hidden)
            bias = self.bias - learning_rate * grad_hidden.sum(axis=0)
            readout = self.readout - learning_rate * (hidden.T @ grad_q)
            offset = self.offset - learning_rate * float(grad_q.sum())
        if not isfinite(offset):
            raise FloatingPointError("network offset must remain finite")
        self.weights, self.bias, self.readout, self.offset = (
            weights,
            bias,
            readout,
            offset,
        )
        return loss

    def snapshot(self) -> NetworkParameters:
        rows = cast(list[list[float]], self.weights.tolist())
        return NetworkParameters(
            weights=tuple(tuple(row) for row in rows),
            bias=tuple(self.bias),
            readout=tuple(self.readout),
            offset=self.offset,
        )

    @classmethod
    def restore(
        cls,
        parameters: NetworkParameters,
        input_size: int,
        hidden_size: int,
    ) -> Self:
        if (
            len(parameters.weights) != input_size
            or any(len(row) != hidden_size for row in parameters.weights)
            or len(parameters.bias) != hidden_size
            or len(parameters.readout) != hidden_size
        ):
            raise ValueError("checkpoint network dimensions do not match configuration")
        return cls(
            weights=np.array(parameters.weights, dtype=np.float64),
            bias=np.array(parameters.bias, dtype=np.float64),
            readout=np.array(parameters.readout, dtype=np.float64),
            offset=parameters.offset,
        )
