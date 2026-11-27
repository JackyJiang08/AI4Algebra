"""Replay the source demonstrations and check that their tactic offsets resolve."""

import json
import subprocess
from pathlib import Path

import pytest

from ai4algebra.lean_bridge.protocol import _worker_environment

ROOT = Path(__file__).resolve().parents[2]
COLLECTION = ROOT / "data/training/subgroups/exercises.jsonl"
MODULE = ROOT / "AI4Algebra/Benchmarks/Gold/ExternalSubgroups.lean"


@pytest.mark.lean
def test_subgroup_demonstrations(tmp_path: Path) -> None:
    source = MODULE.read_text(encoding="utf-8")
    audit = [source]
    seen: set[str] = set()
    for line in COLLECTION.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        task = row["id"]
        assert task not in seen and set(row["requires"]) <= seen
        seen.add(task)
        assert row["split"] == "train"
        assert source.count(row["solution_lean"] + "\n") == 1
        assert row["solution_lean"].startswith(
            row["lean_statement"].split("?_")[0].rstrip().removesuffix(":=").rstrip()
        )
        lines = row["solution_lean"].splitlines()
        assert len(row["tactics"]) > 1
        positions = [(step["line"], step["column"]) for step in row["tactics"]]
        assert positions == sorted(set(positions))
        for step in row["tactics"]:
            tail = lines[step["line"] - 1][step["column"] - 1 :].split("--")[0].rstrip()
            assert tail == step["source_line_tail"]
            assert tail.split()[0] == step["tactic"]
        name = row["qualified_name"]
        audit.extend(
            [
                "run_cmd do",
                f"  for ax in (← Lean.collectAxioms ``{name}) do",
                "    unless ax ∈ ([``propext, ``Classical.choice, ``Quot.sound] : List Lean.Name) do",
                '      throwError "Unexpected axiom: {ax}"',
            ]
        )
    assert len(seen) == 11
    script = tmp_path / "ReplayReferences.lean"
    script.write_text("\n".join(audit), encoding="utf-8")
    result = subprocess.run(
        ["lake", "env", "lean", str(script)],
        cwd=ROOT,
        env=_worker_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
