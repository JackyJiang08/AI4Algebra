"""Check selected Stacks types, dependency closures, and typed proofs in Lean."""

import json
import subprocess
from itertools import combinations
from pathlib import Path

import pytest

from ai4algebra.contracts import Argument, Candidate
from ai4algebra.corpus import Corpus
from ai4algebra.formalization import ReferenceType
from ai4algebra.verification import Verifier

pytestmark = pytest.mark.lean
ROOT = Path(__file__).resolve().parents[2]
BENCHMARKS = ROOT / "AI4Algebra/Benchmarks"
NAMESPACE = "AI4Algebra.Benchmarks"

STEPS = {
    "stacks-00E5-image": (
        Candidate(operation="rewrite", goal_id="g0", lemma="range_comap_of_surjective"),
        Candidate(operation="rewrite", goal_id="g0", lemma="Ideal.mk_ker"),
        Candidate(
            operation="exact", goal_id="g0", lemma="Ideal.Quotient.mk_surjective"
        ),
    ),
    "stacks-00GJ": (
        Candidate(operation="constructor", goal_id="g0"),
        Candidate(operation="intro", goal_id="g0"),
        Candidate(
            operation="exact",
            goal_id="g0",
            lemma="Module.Finite.of_restrictScalars_finite",
            arguments=tuple(
                Argument(kind="local", reference=local) for local in ("l0", "l1", "l2")
            ),
        ),
        Candidate(operation="intro", goal_id="g0"),
        Candidate(
            operation="exact",
            goal_id="g0",
            lemma="Module.Finite.trans",
            arguments=tuple(
                Argument(kind="local", reference=local) for local in ("l1", "l2")
            ),
        ),
    ),
    "stacks-05CI": (
        Candidate(operation="rewrite", goal_id="g0", lemma="LinearMap.rTensor_comp"),
        Candidate(operation="rewrite", goal_id="g0", lemma="LinearMap.coe_comp"),
        Candidate(operation="apply", goal_id="g0", lemma="Function.Injective.comp"),
        Candidate(operation="apply", goal_id="g0", local_id="l14"),
        Candidate(operation="apply", goal_id="g0", local_id="l13"),
    ),
}


def audit_script(
    imports: tuple[str, ...], tracked: tuple[str, ...], premises: tuple[str, ...]
) -> list[str]:
    """Use the observer's real expression serializer on kernel declaration types."""
    observer = (ROOT / "AI4Algebra/Bridge/Main.lean").read_text(encoding="utf-8")
    serializer = observer[
        observer.index("private def binderKind ") : observer.index(
            "private def exportGoal "
        )
    ]
    script = ["import Lean", *[f"import {module}" for module in imports]]
    for path in (
        BENCHMARKS / "StacksStatements.lean",
        BENCHMARKS / "Gold/Stacks.lean",
        ROOT / "tests/fixtures/corpus/audit.lean",
    ):
        script.extend(
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.startswith("import ")
        )
    script.extend(
        [
            serializer,
            """def exportPremise (name : Name) : CommandElabM Unit := do
  let info ← getConstInfo name
  let statement ← liftTermElabM <| ppExpr info.type
  let entry := Json.mkObj [
    ("name", toJson name),
    ("statement", toJson statement.pretty),
    ("expression", toJson ((encodeExpr {} info.type).compress))]
  logInfo m!"PREMISE {entry.compress}"
""",
        ]
    )
    names = "[" + ", ".join("`" + name for name in tracked) + "]"
    script.extend(f"run_cmd checkDependencies {names} `{name}" for name in tracked)
    script.extend(f"run_cmd exportPremise `{name}" for name in premises)
    return script


def type_definition(name: str, reference: ReferenceType) -> str:
    universes = ".{" + ", ".join(reference.universes) + "}"
    binders = "∀ " + " ".join(reference.binders) + ", "
    return f"set_option linter.unusedVariables false in\ndef {name}{universes} : Prop := {binders}{reference.conclusion}"


def run_audit(tmp_path: Path, script: list[str]) -> list[str]:
    path = tmp_path / "StacksAudit.lean"
    path.write_text("\n".join(script) + "\n", encoding="utf-8")
    process = subprocess.run(
        ["lake", "env", "lean", "--threads=1", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    return process.stdout.splitlines()


def test_pinned_stacks_types_and_signatures(tmp_path: Path) -> None:
    corpus = Corpus.open(ROOT / "data/manifests/stacks-pilot.json")
    imports = tuple(
        sorted({module for problem in corpus.problems() for module in problem.imports})
    )
    tracked = tuple(
        item.name
        for item in corpus.manifest.declarations
        if item.module != NAMESPACE + ".StacksTasks"
    )
    premises = tuple(
        item.name
        for item in corpus.manifest.declarations
        if item.disposition == "premise"
    )
    script = audit_script(imports, tracked, premises)
    keys = {}
    tracked_names = "[" + ", ".join("`" + name for name in tracked) + "]"
    for problem in corpus.problems():
        evidence = corpus.mapping(problem.task_id)
        short = problem.lean_name.rsplit(".", 1)[1]
        scope = f"AuditedTypes.{short}"
        script.extend(
            (
                type_definition(
                    problem.lean_name,
                    ReferenceType(
                        universes=problem.universes,
                        binders=problem.binders,
                        conclusion=problem.lean_statement,
                    ),
                ),
                type_definition(scope, evidence.reference_type),
                f"run_cmd checkExercise `{NAMESPACE}.StacksStatements.{short} `{problem.lean_name} "
                f"`{scope} `{NAMESPACE}.Gold.Stacks.{short}",
                f"run_cmd checkDependencies {tracked_names} `{NAMESPACE}.Gold.Stacks.{short}",
            )
        )
        assert evidence.check is not None
        keys[problem.lean_name] = evidence.check.reference_type_key
    for first, second in combinations(corpus.problems(), 2):
        script.append(
            f"run_cmd checkDistinctFamilies `{first.lean_name} `{second.lean_name}"
        )
    audited = run_audit(tmp_path, script)
    assert {
        parts[0]: parts[1]
        for line in audited
        if "TYPE_KEY " in line
        for parts in (line.partition("TYPE_KEY ")[2].split(),)
    } == keys
    signatures = json.loads(
        (ROOT / "data/formalizations/stacks-signatures.json").read_bytes()
    )
    saved = {
        (row["name"], row["statement"], row["expression"])
        for group in signatures["groups"]
        for row in group["premises"]
    }
    assert {
        (row["name"], row["statement"], row["expression"])
        for line in audited
        if "PREMISE " in line
        for row in (json.loads(line.partition("PREMISE ")[2]),)
    } == saved
    dependency_rows = {
        parts[0]: (parts[1], set(parts[2].split(",")) if parts[2] else set())
        for line in audited
        if "DEPENDENCIES " in line
        for parts in (line.partition("DEPENDENCIES ")[2].split(" | "),)
    }
    for item in corpus.manifest.declarations:
        if item.name in tracked:
            assert dependency_rows[item.name] == (item.module, set(item.depends_on))
    for problem in corpus.problems():
        short = problem.lean_name.rsplit(".", 1)[1]
        _, dependencies = dependency_rows[f"{NAMESPACE}.Gold.Stacks.{short}"]
        assert not dependencies.intersection(
            corpus.eligibility_policy(problem).forbidden_declarations
        )


def test_native_verifier_accepts_all_pilot_certificates() -> None:
    corpus = Corpus.open(ROOT / "data/manifests/stacks-pilot.json")
    verifier = Verifier(ROOT)
    for problem in corpus.problems():
        policy = corpus.eligibility_policy(problem)
        certificate = verifier.build_certificate(
            problem, STEPS[problem.task_id], policy
        )
        verdict = verifier.verify(problem, certificate, policy)
        assert verdict.status == "accepted", (problem.task_id, verdict.diagnostics)
        assert not (set(verdict.dependencies) & set(policy.forbidden_declarations))
        if problem.task_id == "stacks-00GJ":
            # This pinned proof exceeded the elementary ceiling. Acceptance must
            # include its complete independently measured closure.
            assert len(verdict.dependencies) == 4912
