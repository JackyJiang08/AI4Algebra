"""Check all selected reference proofs against their independent public case types."""

import json
import subprocess
from pathlib import Path

import pytest

from ai4algebra.lean_bridge.protocol import _worker_environment

pytestmark = pytest.mark.lean
_ROOT = Path(__file__).resolve().parents[2]
_MODULES = (
    "AI4Algebra.Benchmarks.Gold.SelectedGroups",
    "AI4Algebra.Benchmarks.Gold.SelectedQuadratic",
)
_EXPECTED_EXERCISES = {9, 11, 15, 16, 22, 23, 25, 26, 27, 31}


def test_selected_reference_types_and_axioms(tmp_path: Path) -> None:
    cases = []
    for filename in ("group_cases.json", "quadratic_cases.json"):
        data = json.loads((_ROOT / "data/selected" / filename).read_bytes())
        assert data["schema_version"] == 1
        cases.extend(data["cases"])
    assert len(cases) == 10
    assert {case["exercise"] for case in cases} == _EXPECTED_EXERCISES

    built = subprocess.run(
        ["lake", "build", *_MODULES],
        cwd=_ROOT,
        env=_worker_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=600,
    )
    (tmp_path / "reference-build.log").write_text(
        built.stdout + built.stderr, encoding="utf-8"
    )
    assert built.returncode == 0, built.stdout + built.stderr

    script = [
        "import Lean",
        *(f"import {module}" for module in _MODULES),
        "set_option autoImplicit false",
        "set_option warningAsError true",
        "set_option linter.unusedVariables false",
        "namespace SelectedReferenceAlignmentCheck",
    ]
    universes = sorted({u for case in cases for u in case["universes"]})
    if universes:
        script.append("universe " + " ".join(universes))
    for case in cases:
        binders = " ".join(case["binders"])
        telescope = f"∀ {binders}, " if binders else ""
        name = case["reference_declaration"]
        script.extend(
            [
                f"example : {telescope}{case['conclusion']} := @{name}",
                "run_cmd do",
                f"  let axioms ← Lean.collectAxioms ``{name}",
                "  for ax in axioms do",
                "    unless ax ∈ ([``propext, ``Classical.choice, ``Quot.sound] : List Lean.Name) do",
                '      throwError "Unapproved reference axiom: {ax}"',
                f"#print axioms {name}",
            ]
        )
    script.append("end SelectedReferenceAlignmentCheck")
    source = tmp_path / "SelectedReferenceAlignment.lean"
    source.write_text("\n".join(script) + "\n", encoding="utf-8")
    checked = subprocess.run(
        ["lake", "env", "lean", str(source)],
        cwd=_ROOT,
        env=_worker_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    (tmp_path / "reference-alignment.log").write_text(
        checked.stdout + checked.stderr, encoding="utf-8"
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
