"""Join the pinned elementary signature extract to the reviewed corpus policy."""

from pathlib import Path

from ai4algebra.contracts import Problem
from ai4algebra.corpus import Corpus, _dependency_closures
from ai4algebra.lean_bridge import environment_digest

from ._elementary_signatures import SIGNATURES
from ._rules import LemmaRule, PremiseIndex

_PINNED_IMPORTS = {
    ("Mathlib.Algebra.Group.Defs",),
    ("Mathlib.Algebra.Ring.Defs",),
}


def elementary_premise_index(
    corpus: Corpus, problem: Problem, project_root: Path
) -> PremiseIndex:
    """Bind observed declaration types to the exact public benchmark environment."""
    policy = corpus.eligibility_policy(problem)
    if (corpus.manifest.corpus_id, corpus.manifest.revision) != ("elementary", "1"):
        raise ValueError(
            "elementary signature extract belongs to another corpus revision"
        )
    if problem.imports not in _PINNED_IMPORTS:
        raise ValueError("elementary signature extract does not cover these imports")
    declarations = {item.name: item for item in corpus.manifest.declarations}
    closures = _dependency_closures(declarations)
    rules = []
    for name in policy.allowed_declarations:
        if name not in SIGNATURES:
            raise ValueError(
                "an allowed elementary declaration lacks a pinned signature"
            )
        statement, expression = SIGNATURES[name]
        rules.append(
            LemmaRule(
                name=name,
                statement=statement,
                expression=expression,
                module=declarations[name].module,
                required_imports=problem.imports,
                dependencies=tuple(sorted(closures[name])),
            )
        )
    return PremiseIndex(
        environment_digest=environment_digest(project_root, problem.imports),
        imports=problem.imports,
        rules=tuple(rules),
    )
