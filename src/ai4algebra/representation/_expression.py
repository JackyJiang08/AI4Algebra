"""Decode the structural expressions emitted by the Lean observer."""

import json
from dataclasses import dataclass, field
from typing import TypeAlias, cast

from ai4algebra.contracts import Goal

Term: TypeAlias = str | int | bool | tuple["Term", ...]
_BINDERS = {"explicit", "implicit", "strict_implicit", "instance"}


def _array(node: object) -> list[object]:
    if not isinstance(node, list):
        raise ValueError("expected a Lean expression array")
    return cast(list[object], node)


def _name(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("expected a Lean name")
    return value


def _natural(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("expected a Lean natural number")
    return value


@dataclass
class Normalizer:
    """Alpha-normalize generated names and check bound references."""

    universe_params: dict[str, int] = field(default_factory=dict)
    universe_mvars: dict[str, int] = field(default_factory=dict)
    expr_mvars: dict[str, int] = field(default_factory=dict)
    free_vars: dict[str, int] = field(default_factory=dict)

    def level(self, encoded: object) -> Term:
        match _array(encoded):
            case ["zero"]:
                return ("zero",)
            case ["succ", child]:
                return ("succ", self.level(child))
            case [("max" | "imax") as tag, lhs, rhs]:
                return (tag, self.level(lhs), self.level(rhs))
            case ["param", name]:
                return (
                    "param",
                    self.universe_params.setdefault(
                        _name(name), len(self.universe_params)
                    ),
                )
            case ["mvar", name]:
                return (
                    "mvar",
                    self.universe_mvars.setdefault(
                        _name(name), len(self.universe_mvars)
                    ),
                )
            case _:
                raise ValueError("unsupported Lean universe expression")

    def expr(self, source: str, *, local_count: int) -> Term:
        try:
            encoded: object = json.loads(source)
            return self._expr(encoded, local_count=local_count, depth=0)
        except (json.JSONDecodeError, RecursionError) as exc:
            raise ValueError("invalid structural Lean expression") from exc

    def _expr(self, encoded: object, *, local_count: int, depth: int) -> Term:
        match _array(encoded):
            case ["bvar", index] if _natural(index) < depth:
                return ("bvar", _natural(index))
            case ["local", index] if _natural(index) < local_count:
                return ("local", _natural(index))
            case ["bvar" | "local", _]:
                raise ValueError("Lean expression has an out-of-scope variable")
            case ["free", name]:
                return (
                    "free",
                    self.free_vars.setdefault(_name(name), len(self.free_vars)),
                )
            case ["mvar", name]:
                return (
                    "mvar",
                    self.expr_mvars.setdefault(_name(name), len(self.expr_mvars)),
                )
            case ["sort", level]:
                return ("sort", self.level(level))
            case ["const", name, levels]:
                return (
                    "const",
                    _name(name),
                    tuple(self.level(level) for level in _array(levels)),
                )
            case ["app", function, argument]:
                return (
                    "app",
                    self._expr(function, local_count=local_count, depth=depth),
                    self._expr(argument, local_count=local_count, depth=depth),
                )
            case [("lam" | "forall") as tag, str(kind), domain, body] if (
                kind in _BINDERS
            ):
                return (
                    tag,
                    kind,
                    self._expr(domain, local_count=local_count, depth=depth),
                    self._expr(body, local_count=local_count, depth=depth + 1),
                )
            case ["let", domain, value, body, bool(nondependent)]:
                return (
                    "let",
                    self._expr(domain, local_count=local_count, depth=depth),
                    self._expr(value, local_count=local_count, depth=depth),
                    self._expr(body, local_count=local_count, depth=depth + 1),
                    nondependent,
                )
            case ["nat", value]:
                return ("nat", _natural(value))
            case ["string", str(value)]:
                return ("string", value)
            case ["proj", name, index, value]:
                return (
                    "proj",
                    _name(name),
                    _natural(index),
                    self._expr(value, local_count=local_count, depth=depth),
                )
            case _:
                raise ValueError("unsupported Lean expression")

    def goals(self, goals: tuple[Goal, ...]) -> tuple[Term, ...]:
        result: list[Term] = []
        for goal in goals:
            self.free_vars.clear()
            locals_: list[Term] = []
            for index, hyp in enumerate(goal.hypotheses):
                locals_.append(
                    (
                        hyp.binder_kind,
                        self.expr(hyp.expression, local_count=index),
                        ()
                        if hyp.value is None
                        else self.expr(hyp.value, local_count=index),
                    )
                )
            result.append(
                (
                    tuple(locals_),
                    self.expr(goal.expression, local_count=len(locals_)),
                )
            )
        return tuple(result)
