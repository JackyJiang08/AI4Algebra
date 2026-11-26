"""Environment-scoped declaration signatures and inexpensive tactic templates."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, TypeAlias, TypedDict

from pydantic import Field, model_validator
from typing_extensions import Self

from ai4algebra.contracts import (
    _COMPUTED_DIGEST,
    Argument,
    Candidate,
    Digest,
    Goal,
    LeanName,
    NonBlank,
    Observation,
    Problem,
    Record,
    digest_json,
)
from ai4algebra.representation import DeclarationSignature
from ai4algebra.representation._expression import Normalizer
from ai4algebra.verification import EligibilityPolicy

GENERATOR_VERSION = "typed-v2"
MAX_OPERANDS = 8
Shape: TypeAlias = tuple[str, int | str, tuple["Shape", ...]]
_EXPLICIT_OPERANDS = {
    "Eq": 2,
    "HEq": 2,
    "HMul.hMul": 2,
    "HAdd.hAdd": 2,
    "HSub.hSub": 2,
    "Inv.inv": 1,
}


def _application(term: object) -> tuple[object, list[object]]:
    args = []
    while isinstance(term, list) and len(term) == 3 and term[0] == "app":
        args.append(term[2])
        term = term[1]
    args.reverse()
    return term, args


def _shape(term: object, binders: int = 0) -> Shape:
    head, args = _application(term)
    if isinstance(head, list) and len(head) >= 2:
        tag, name = head[:2]
        if tag == "const" and isinstance(name, str):
            if name == "OfNat.ofNat" and len(args) == 3:
                return _shape(args[1], binders)
            arity = _EXPLICIT_OPERANDS.get(name, len(args))
            return "const", name, tuple(_shape(arg, binders) for arg in args[-arity:])
        if tag == "bvar" and type(name) is int and 0 <= name < binders:
            return "variable", binders - 1 - name, ()
        if tag in ("local", "nat") and type(name) is int:
            return tag, name, ()
    # Opaque structure still provides a deterministic feature for exact matching.
    return "opaque", digest_json(term), ()


def _match(pattern: Shape, target: Shape, bindings: dict[int, Shape]) -> bool:
    kind, name, args = pattern
    if kind == "variable" and isinstance(name, int):
        return bindings.setdefault(name, target) == target
    return (
        pattern[:2] == target[:2]
        and len(args) == len(target[2])
        and all(_match(a, b, bindings) for a, b in zip(args, target[2], strict=True))
    )


def _terms(shape: Shape) -> Iterator[Shape]:
    yield shape
    for term in shape[2]:
        yield from _terms(term)


def _constants(expression: str) -> set[str]:
    pending: list[object] = [json.loads(expression)]
    names: set[str] = set()
    while pending:
        term = pending.pop()
        if isinstance(term, list):
            if len(term) == 3 and term[0] == "const" and isinstance(term[1], str):
                names.add(term[1])
            pending.extend(term)
    return names


@dataclass(frozen=True)
class _RuleShape:
    binders: tuple[tuple[str, Shape], ...]
    conclusion: Shape


class _CandidateFlags(TypedDict):
    goal_id: str
    generator_version: str


class _LemmaFlags(_CandidateFlags):
    lemma: str


def _parse_rule(source: str) -> _RuleShape:
    term = json.loads(source)
    binders: list[tuple[str, Shape]] = []
    while isinstance(term, list) and len(term) == 4 and term[0] == "forall":
        kind = term[1]
        if kind not in ("explicit", "implicit", "strict_implicit", "instance"):
            raise ValueError("invalid lemma binder kind")
        binders.append((kind, _shape(term[2], len(binders))))
        term = term[3]
    if not isinstance(term, list) or not term:
        raise ValueError("lemma type is not an encoded Lean expression")
    return _RuleShape(tuple(binders), _shape(term, len(binders)))


class LemmaRule(Record):
    name: LeanName
    statement: NonBlank
    expression: NonBlank
    module: LeanName
    required_imports: tuple[LeanName, ...] = ()
    # Kernel-generated private names include numeric components. These are audit
    # evidence only, never parsed as tactic operands (which retain LeanName).
    dependencies: tuple[NonBlank, ...] = ()
    type_digest: Digest = Field(
        default="", validate_default=False, description=_COMPUTED_DIGEST
    )
    dependency_digest: Digest = Field(
        default="", validate_default=False, description=_COMPUTED_DIGEST
    )

    @model_validator(mode="after")
    def _validate_type(self) -> Self:
        Normalizer().expr(self.expression, local_count=0)
        calculated = digest_json((self.statement, self.expression))
        if self.type_digest and self.type_digest != calculated:
            raise ValueError("lemma type digest does not match encoded type")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("duplicate lemma dependency")
        dependency_digest = digest_json((self.module, sorted(self.dependencies)))
        if self.dependency_digest and self.dependency_digest != dependency_digest:
            raise ValueError("lemma dependency digest does not match closure")
        object.__setattr__(self, "type_digest", calculated)
        object.__setattr__(self, "dependency_digest", dependency_digest)
        return self

    @property
    def signature(self) -> DeclarationSignature:
        return DeclarationSignature(name=self.name, expression=self.expression)


class PremiseIndex(Record):
    """An immutable index of reviewed signatures for one pinned import environment."""

    environment_digest: Digest
    imports: tuple[LeanName, ...]
    rules: tuple[LemmaRule, ...]

    @model_validator(mode="after")
    def _validate_rules(self) -> Self:
        if len({rule.name for rule in self.rules}) != len(self.rules):
            raise ValueError("duplicate rule in premise index")
        return self

    def retrieve(
        self,
        observation: Observation,
        eligibility: EligibilityPolicy,
        k: int,
        *,
        problem: Problem | None = None,
    ) -> tuple[LemmaRule, ...]:
        if type(k) is not int or k < 0:
            raise ValueError("retrieval limit must be a nonnegative integer")
        index = PremiseIndex.from_json(self.to_json())
        eligibility = EligibilityPolicy.from_json(eligibility.to_json())
        if (
            index.environment_digest != observation.snapshot.environment_digest
            or index.imports != eligibility.allowed_imports
        ):
            raise ValueError("premise index environment or imports are incompatible")
        allowed = set(eligibility.allowed_declarations)
        forbidden = set(eligibility.forbidden_declarations)
        if problem is not None:
            problem = Problem.from_json(problem.to_json())
            eligibility.validate_for(problem, ())
            forbidden.add(problem.lean_name)
        imports = set(index.imports)
        heads = {_shape(json.loads(goal.expression))[:2] for goal in observation.goals}
        eligible = [
            rule
            for rule in index.rules
            if rule.name in allowed
            and not ({rule.name, *rule.dependencies} & forbidden)
            and not (_constants(rule.expression) & forbidden)
            and (
                set(rule.required_imports or (rule.module,)) <= imports
                or (not rule.required_imports and rule.module.split(".")[0] == "Init")
            )
            and not any(
                rule.module == module or rule.module.startswith(module + ".")
                for module in eligibility.forbidden_imports
            )
        ]
        return tuple(
            sorted(
                eligible,
                key=lambda rule: (
                    _parse_rule(rule.expression).conclusion[:2] not in heads,
                    rule.name,
                ),
            )[:k]
        )


def referenced_declarations(candidate: Candidate) -> set[str]:
    declarations = {arg.reference for arg in candidate.arguments if arg.kind == "lemma"}
    declarations.update(candidate.simp_lemmas)
    if candidate.lemma is not None:
        declarations.add(candidate.lemma)
    return declarations


def instantiate(rule: LemmaRule, goal: Goal) -> tuple[Candidate, ...]:
    """Propose concrete local arguments and a Lean-inferred applicability probe."""
    matched, inferred = _instantiate(rule, goal)
    return (*matched, *inferred)


def _instantiate(
    rule: LemmaRule, goal: Goal
) -> tuple[tuple[Candidate, ...], tuple[Candidate, ...]]:
    rule_shape = _parse_rule(rule.expression)
    goal_shape = _shape(json.loads(goal.expression))
    fields: _LemmaFlags = {
        "goal_id": goal.goal_id,
        "lemma": rule.name,
        "generator_version": GENERATOR_VERSION,
    }
    suggestions = []
    inferred = []
    bindings: dict[int, Shape] = {}
    if _match(rule_shape.conclusion, goal_shape, bindings):
        arguments: list[Argument] = []
        order = range(len(rule_shape.binders))
        for position, (kind, domain) in zip(order, rule_shape.binders, strict=True):
            if kind != "explicit":
                continue
            assignment = bindings.get(position)
            if (
                assignment is not None
                and assignment[0] == "local"
                and isinstance(assignment[1], int)
                and 0 <= assignment[1] < len(goal.hypotheses)
            ):
                arguments.append(
                    Argument(
                        kind="local", reference=goal.hypotheses[assignment[1]].local_id
                    )
                )
                continue
            if assignment is not None:
                break
            for hyp in goal.hypotheses:
                trial = bindings.copy()
                if _match(domain, _shape(json.loads(hyp.expression)), trial):
                    bindings = trial
                    arguments.append(Argument(kind="local", reference=hyp.local_id))
                    break
            else:
                break
        else:
            if len(arguments) <= MAX_OPERANDS:
                suggestions.append(
                    Candidate(operation="exact", arguments=tuple(arguments), **fields)
                )
        suggestions.append(Candidate(operation="apply", **fields))
    kind, name, args = rule_shape.conclusion
    terms = tuple(_terms(goal_shape))
    if kind == "const" and name in ("Eq", "Iff") and len(args) == 2:
        directions: tuple[Literal["forward", "backward"], ...] = ("forward", "backward")
        for direction, pattern in zip(directions, args, strict=True):
            if pattern[0] == "variable":
                continue
            if any(_match(pattern, term, {}) for term in terms):
                suggestions.append(
                    Candidate(operation="rewrite", direction=direction, **fields)
                )
            # Coercions, implicit arguments and derived instances can obscure a
            # surface match. Let Lean decide when the rigid outer head agrees.
            elif pattern[0] == "const" and any(
                pattern[:2] == term[:2] for term in terms
            ):
                inferred.append(
                    Candidate(operation="rewrite", direction=direction, **fields)
                )
    if (
        kind == "const"
        and rule_shape.conclusion[:2] == goal_shape[:2]
        and not any(candidate.operation == "apply" for candidate in suggestions)
    ):
        inferred.append(Candidate(operation="apply", **fields))
    return tuple(suggestions), tuple(inferred)
