"""Bind Stacks pilot premises to checked kernel signatures and exact imports."""

from pathlib import Path

from pydantic import model_validator
from typing_extensions import Self

from ai4algebra.candidates import LemmaRule, PremiseIndex
from ai4algebra.contracts import Digest, LeanName, NonBlank, Problem, Record
from ai4algebra.corpus import Corpus, _dependency_closures, _public_path
from ai4algebra.lean_bridge import environment_digest

_SIGNATURES = "data/formalizations/stacks-signatures.json"


class _Signature(Record):
    name: LeanName
    statement: NonBlank
    expression: NonBlank


class _ImportGroup(Record):
    imports: tuple[LeanName, ...]
    environment_digest: Digest
    premises: tuple[_Signature, ...]


class _SignatureAsset(Record):
    groups: tuple[_ImportGroup, ...]

    @model_validator(mode="after")
    def _unique_groups(self) -> Self:
        if len({group.imports for group in self.groups}) != len(self.groups):
            raise ValueError("duplicate Stacks signature import group")
        return self


def stacks_premise_index(corpus: Corpus, problem: Problem, root: Path) -> PremiseIndex:
    """Return the reviewed signature group for one admitted Stacks task."""
    if (corpus.manifest.corpus_id, corpus.manifest.revision) != ("stacks-pilot", "1"):
        raise ValueError("Stacks signature extract belongs to another corpus revision")
    policy = corpus.eligibility_policy(problem)
    pinned = environment_digest(root, problem.imports)
    asset = _SignatureAsset.from_json(
        _public_path(root.resolve(), _SIGNATURES).read_bytes()
    )
    group = next(
        (item for item in asset.groups if item.imports == problem.imports), None
    )
    if group is None or group.environment_digest != pinned:
        raise ValueError("Stacks signatures do not match the pinned task imports")
    signatures = {premise.name: premise for premise in group.premises}
    if (
        len(signatures) != len(group.premises)
        or not set(policy.allowed_declarations) <= signatures.keys()
    ):
        raise ValueError("missing or duplicate reviewed Stacks signature")
    declarations = {item.name: item for item in corpus.manifest.declarations}
    closures = _dependency_closures(declarations)
    return PremiseIndex(
        environment_digest=pinned,
        imports=problem.imports,
        rules=tuple(
            LemmaRule(
                name=name,
                statement=signatures[name].statement,
                expression=signatures[name].expression,
                module=declarations[name].module,
                required_imports=problem.imports,
                dependencies=tuple(sorted(closures[name])),
            )
            for name in policy.allowed_declarations
        ),
    )
