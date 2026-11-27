"""A shared scalar NumPy network over concatenated state and candidate vectors."""

from dataclasses import dataclass
from math import isfinite
from typing import cast

import numpy as np
from numpy.typing import NDArray
from pydantic import SerializerFunctionWrapHandler, model_serializer
from typing_extensions import Self

from ai4algebra.contracts import Record

from ._records import Activation, DDQNConfig

FloatArray = NDArray[np.float64]


class DenseParameters(Record):
    weights: tuple[tuple[float, ...], ...]
    bias: tuple[float, ...]


class NetworkParameters(DenseParameters):
    readout: tuple[float, ...]
    offset: float
    extra_layers: tuple[DenseParameters, ...] = ()

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, object]:
        data = cast(dict[str, object], handler(self))
        if not self.extra_layers:
            data.pop("extra_layers", None)
        return data


@dataclass
class DenseLayer:
    weights: FloatArray
    bias: FloatArray

    def snapshot(self) -> DenseParameters:
        return DenseParameters(
            weights=tuple(map(tuple, self.weights)), bias=tuple(self.bias)
        )


def _sigmoid(x: FloatArray) -> FloatArray:
    # Use only nonpositive exponents, including for large negative preactivations.
    exp = np.exp(-np.abs(x))
    return np.where(x >= 0, 1.0, exp) / (1.0 + exp)


@dataclass
class ScalarQ:
    layers: list[DenseLayer]
    activation: Activation
    readout: FloatArray
    offset: float

    @classmethod
    def initialize(cls, input_size: int, config: DDQNConfig) -> Self:
        rng = np.random.default_rng(config.seed)
        layers = []
        for _ in range(config.hidden_layers):
            weights = rng.normal(
                0.0, np.sqrt(2.0 / input_size), (input_size, config.hidden_size)
            )
            layers.append(DenseLayer(weights, np.zeros(config.hidden_size)))
            input_size = config.hidden_size
        return cls(
            layers,
            config.activation,
            rng.normal(0.0, np.sqrt(1.0 / input_size), input_size),
            0.0,
        )

    def copy(self) -> Self:
        return type(self)(
            [
                DenseLayer(layer.weights.copy(), layer.bias.copy())
                for layer in self.layers
            ],
            self.activation,
            self.readout.copy(),
            self.offset,
        )

    def _forward(
        self,
        pairs: FloatArray,
        cache: list[tuple[FloatArray, FloatArray]] | None = None,
    ) -> tuple[FloatArray, FloatArray]:
        hidden = pairs
        with np.errstate(over="raise", invalid="raise"):
            for layer in self.layers:
                z = np.einsum("bi,ih->bh", hidden, layer.weights) + layer.bias
                if self.activation == "silu":
                    sigmoid = _sigmoid(z)
                    activated = z * sigmoid
                    if cache is not None:
                        cache.append((hidden, sigmoid + activated * (1.0 - sigmoid)))
                else:
                    activated = np.maximum(z, 0.0)
                    if cache is not None:
                        cache.append((hidden, (z > 0.0).astype(np.float64)))
                hidden = activated
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
        cache: list[tuple[FloatArray, FloatArray]] = []
        hidden, scores = self._forward(pairs, cache)
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
            readout = self.readout - learning_rate * (hidden.T @ grad_q)
            offset = self.offset - learning_rate * float(grad_q.sum())
            grad = grad_q[:, None] * self.readout
            updated = []
            for index in reversed(range(len(self.layers))):
                layer = self.layers[index]
                inputs, derivative = cache[index]
                delta = grad * derivative
                updated.append(
                    DenseLayer(
                        layer.weights - learning_rate * (inputs.T @ delta),
                        layer.bias - learning_rate * delta.sum(axis=0),
                    )
                )
                if index:
                    grad = delta @ layer.weights.T
        if not isfinite(offset):
            raise FloatingPointError("network offset must remain finite")
        self.layers, self.readout, self.offset = updated[::-1], readout, offset
        return loss

    def snapshot(self) -> NetworkParameters:
        first, *rest = (layer.snapshot() for layer in self.layers)
        return NetworkParameters(
            weights=first.weights,
            bias=first.bias,
            extra_layers=tuple(rest),
            readout=tuple(self.readout),
            offset=self.offset,
        )

    @classmethod
    def restore(
        cls, parameters: NetworkParameters, input_size: int, config: DDQNConfig
    ) -> Self:
        size = config.hidden_size
        layers = []
        if (
            len(parameters.extra_layers) + 1 != config.hidden_layers
            or len(parameters.readout) != size
        ):
            raise ValueError("checkpoint network dimensions do not match configuration")
        for params in (parameters, *parameters.extra_layers):
            if (
                len(params.weights) != input_size
                or any(len(row) != size for row in params.weights)
                or len(params.bias) != size
            ):
                raise ValueError(
                    "checkpoint network dimensions do not match configuration"
                )
            layers.append(DenseLayer(np.array(params.weights), np.array(params.bias)))
            input_size = size
        return cls(
            layers, config.activation, np.array(parameters.readout), parameters.offset
        )

    def freeze(self) -> None:
        for layer in self.layers:
            layer.weights.setflags(write=False)
            layer.bias.setflags(write=False)
        self.readout.setflags(write=False)
