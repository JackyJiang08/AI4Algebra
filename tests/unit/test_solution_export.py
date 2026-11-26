import json
from pathlib import Path

import pytest

from ai4algebra.cli import main

_ROOT = Path(__file__).resolve().parents[2]


def test_solution_export_limits_manifest_to_train_and_preserves_lean_syntax(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI4ALGEBRA_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AI4ALGEBRA_ALLOW_PAID_API", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert (
        main(
            [
                "export-tactics",
                "--project-root",
                str(_ROOT),
                "--include-selected",
                "--output",
                str(tmp_path),
            ]
        )
        == 0
    )
    elementary = json.loads((tmp_path / "elementary-tactics.json").read_bytes())
    assert elementary["scope"] == "manifest_train"
    solutions = elementary["sources"][0]["solutions"]
    assert [s["task_id"] for s in solutions] == [
        "group-inverse-identity",
        "group-ordered-inverse",
    ]
    assert solutions[0]["proof_body"] == " by\n  rw [mul_inv_cancel, mul_one]"

    selected = json.loads((tmp_path / "selected-development-tactics.json").read_bytes())
    assert selected["scope"] == "selected_development_archive"
    assert selected["partition_digest"] is None
    exercises = {
        s["task_id"]: s
        for source in selected["sources"]
        for s in source["solutions"]
        if s["task_id"] is not None
    }
    assert len(exercises) == 10
    assert exercises["exercise-11"]["proof_kind"] == "term"
    assert "(by decide)" in exercises["exercise-11"]["proof_body"]
    assert "| cons x xs ih =>\n    simp only" in exercises["exercise-15"]["proof_body"]
    assert "linear_combination" in exercises["exercise-9"]["proof_body"]
    assert "#print axioms" not in exercises["exercise-31"]["proof_body"]


def test_stacks_export_excludes_full_held_out_mappings(tmp_path: Path) -> None:
    assert (
        main(
            [
                "export-tactics",
                "--manifest",
                str(_ROOT / "data/manifests/stacks-pilot.json"),
                "--output",
                str(tmp_path),
            ]
        )
        == 0
    )
    stacks = json.loads((tmp_path / "stacks-pilot-tactics.json").read_bytes())
    solutions = stacks["sources"][0]["solutions"]
    assert [s["task_id"] for s in solutions] == ["stacks-00E5-image"]
    assert "Ideal.Quotient.mk_surjective" in solutions[0]["proof_body"]
