"""Batch-check the elementary statements, premise closures and protected proofs."""

import subprocess
from itertools import combinations
from pathlib import Path

import pytest

from ai4algebra.contracts import Argument, Candidate
from ai4algebra.corpus import Corpus
from ai4algebra.formalization import ReferenceType
from ai4algebra.verification import Verifier

pytestmark = pytest.mark.lean
_ROOT = Path(__file__).resolve().parents[2]
_BENCHMARKS = _ROOT / "AI4Algebra/Benchmarks"
_NAMESPACE = "AI4Algebra.Benchmarks"
_REPLAY = "AI4Algebra.Verification.Replay"


def _rewrites(*lemmas: str) -> tuple[Candidate, ...]:
    return tuple(
        Candidate(operation="rewrite", goal_id="g0", lemma=lemma) for lemma in lemmas
    )


_STEPS = {
    "group-inverse-identity": _rewrites("mul_inv_cancel", "mul_one"),
    "group-ordered-inverse": _rewrites(
        "mul_inv_cancel", "mul_one", "mul_assoc", "mul_inv_cancel", "mul_one"
    ),
    "ring-distribute-sub": _rewrites("mul_add", "mul_sub"),
    "ring-add-cancel-pair": (
        Candidate(operation="constructor", goal_id="g0"),
        Candidate(
            operation="exact",
            goal_id="g1",
            lemma="add_right_cancel",
            arguments=(Argument(kind="local", reference="l9"),),
        ),
        Candidate(
            operation="exact",
            goal_id="g0",
            lemma="add_left_cancel",
            arguments=(Argument(kind="local", reference="l8"),),
        ),
    ),
}


def _type_definition(name: str, reference: ReferenceType) -> str:
    levels = ".{" + ", ".join(reference.universes) + "}" if reference.universes else ""
    telescope = "∀ " + " ".join(reference.binders) + ", " if reference.binders else ""
    return (
        "set_option linter.unusedVariables false in\n"
        f"def {name}{levels} : Prop := {telescope}{reference.conclusion}"
    )


def _body(source: str) -> str:
    """Join test-only modules into one Lean invocation with a common import preamble."""
    return "\n".join(
        line for line in source.splitlines() if not line.startswith("import ")
    )


def test_pinned_lean_checks_all_elementary_statements_and_proofs(
    tmp_path: Path,
) -> None:
    corpus = Corpus.open(_ROOT / "data/manifests/elementary.json")
    built = subprocess.run(
        ["lake", "build", _REPLAY],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    verifier = Verifier(_ROOT)
    modules = sorted({module for item in corpus.problems() for module in item.imports})
    script = [
        "import Lean",
        f"import {_REPLAY}",
        *(f"import {module}" for module in modules),
        "set_option autoImplicit false",
        "set_option warningAsError true",
    ]
    for problem in corpus.problems():
        short_name = problem.lean_name.rsplit(".", 1)[1]
        script.extend(
            (
                "run_cmd do",
                "  let env ← Lean.getEnv",
                f"  if env.contains `{problem.lean_name} ||",
                f"      env.contains `{_NAMESPACE}.Gold.{short_name} then",
                '    throwError "a public task import contains an answer declaration"',
            )
        )
    script.extend(
        _body(path.read_text(encoding="utf-8"))
        for path in (
            _BENCHMARKS / "Statements.lean",
            _ROOT / "tests/fixtures/corpus/audit.lean",
        )
    )
    # Compile the verifier's typed scripts before loading protected reference proofs.
    # The branching trace solves the right-hand goal first.
    for problem in corpus.problems():
        certificate = verifier.build_certificate(
            problem, _STEPS[problem.task_id], corpus.eligibility_policy(problem)
        )
        script.append(_body(certificate.proof))
    script.append(_body((_BENCHMARKS / "Gold.lean").read_text(encoding="utf-8")))

    expected_keys: dict[str, str] = {}
    for problem in corpus.problems():
        short_name = problem.lean_name.rsplit(".", 1)[1]
        source_type = f"{_NAMESPACE}.Statements.{short_name}"
        proof = f"{_NAMESPACE}.Gold.{short_name}"
        manifest_name = f"ManifestTypes.{short_name}"
        evidence_type = f"EvidenceTypes.{short_name}"
        evidence = corpus.mapping(problem.task_id)
        manifest_type = ReferenceType(
            universes=problem.universes,
            binders=problem.binders,
            conclusion=problem.lean_statement,
        )
        script.extend(
            (
                _type_definition(manifest_name, manifest_type),
                _type_definition(evidence_type, evidence.reference_type),
                f"run_cmd checkExercise `{source_type} `{manifest_name} "
                f"`{evidence_type} `{proof}",
                f"run_cmd checkExercise `{source_type} `{manifest_name} "
                f"`{evidence_type} `{problem.lean_name}",
            )
        )
        assert evidence.check is not None
        assert evidence.check.reference_type_key is not None
        expected_keys[manifest_name] = evidence.check.reference_type_key

    for first, second in combinations(corpus.problems(), 2):
        if first.family_id != second.family_id:
            first_type = "ManifestTypes." + first.lean_name.rsplit(".", 1)[1]
            second_type = "ManifestTypes." + second.lean_name.rsplit(".", 1)[1]
            script.append(f"run_cmd checkDistinctFamilies `{first_type} `{second_type}")

    # Compare source types with an alpha-renaming and genuinely different,
    # well-formed candidate statements within the same real Lean session.
    script.extend(
        (
            "def Renamed.{v} : Prop := ∀ (X : Type v) [Group X] (x y : X), x * (y * y⁻¹) = x",
            f"run_cmd checkExercise `{_NAMESPACE}.Statements.group_inverse_identity `Renamed "
            f"`EvidenceTypes.group_inverse_identity `{_NAMESPACE}.Gold.group_inverse_identity",
            "def Weakened.{u} : Prop := ∀ (G : Type u) [Group G] (a _ : G), a = a",
            "def Reversed.{u} : Prop := ∀ (G : Type u) [Group G] (a b c : G), "
            "((a * b) * (c * b⁻¹)) * c⁻¹ = a",
            f"run_cmd checkDistinctFamilies `{_NAMESPACE}.Statements.group_inverse_identity `Weakened",
            f"run_cmd checkDistinctFamilies `{_NAMESPACE}.Statements.group_ordered_inverse `Reversed",
        )
    )
    expected_keys["Renamed"] = expected_keys["ManifestTypes.group_inverse_identity"]

    declarations = tuple(
        entry for entry in corpus.manifest.declarations if entry.module in modules
    )
    protected = tuple(
        f"{_NAMESPACE}.Gold.{item.lean_name.rsplit('.', 1)[1]}"
        for item in corpus.problems()
    )
    tracked = (
        "["
        + ", ".join(
            "`" + name for name in (*(item.name for item in declarations), *protected)
        )
        + "]"
    )
    for entry in declarations:
        script.append(f"run_cmd checkDependencies {tracked} `{entry.name}")
    for problem in corpus.problems():
        short_name = problem.lean_name.rsplit(".", 1)[1]
        script.append(
            f"run_cmd checkDependencies {tracked} `{_NAMESPACE}.Gold.{short_name}"
        )
        script.append(f"run_cmd checkDependencies {tracked} `{problem.lean_name}")

    path = tmp_path / "ElementaryAudit.lean"
    path.write_text("\n".join(script) + "\n", encoding="utf-8")
    process = subprocess.run(
        ["lake", "env", "lean", "--threads=1", str(path)],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=90,
    )
    assert process.returncode == 0, process.stdout + process.stderr

    keys: dict[str, str] = {}
    dependencies: dict[str, tuple[str, set[str]]] = {}
    for line in process.stdout.splitlines():
        if "TYPE_KEY " in line:
            name, key = line.partition("TYPE_KEY ")[2].split()
            keys[name] = key
        if "DEPENDENCIES " in line:
            name, module, deps = line.partition("DEPENDENCIES ")[2].split(" | ")
            dependencies[name] = (module, set(deps.split(",")) if deps else set())
    assert keys == expected_keys
    for item in declarations:
        assert dependencies[item.name] == (item.module, set(item.depends_on))
    for problem in corpus.problems():
        short_name = problem.lean_name.rsplit(".", 1)[1]
        policy = corpus.eligibility_policy(problem)
        _, used = dependencies[f"{_NAMESPACE}.Gold.{short_name}"]
        assert used <= set(policy.allowed_declarations)
        assert not used.intersection(policy.forbidden_declarations)
        _, runtime_used = dependencies[problem.lean_name]
        assert runtime_used <= set(policy.allowed_declarations)
