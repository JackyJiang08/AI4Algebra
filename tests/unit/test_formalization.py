"""Check mapping evidence identity and benchmark admission rules."""

import json
from pathlib import Path

import pytest

from ai4algebra.contracts import Problem
from ai4algebra.corpus import Corpus
from ai4algebra.formalization import (
    MappingEvidence,
    ReferenceType,
    StatementCheck,
    validate_mapping,
)

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / "data/manifests/elementary.json"
_MAPPINGS = _ROOT / "data/formalizations/elementary.json"


def test_elaboration_alone_cannot_grant_or_retain_validated_status() -> None:
    corpus = Corpus.open(_MANIFEST)
    problem = corpus.problems("train")[0]
    evidence = corpus.mapping(problem.task_id)
    checked = evidence.check
    assert checked is not None

    def elaborates(task: Problem, reference: ReferenceType) -> StatementCheck:
        assert task == problem
        assert reference == evidence.reference_type
        return StatementCheck.model_validate(
            checked.model_dump()
            | {
                "result": "elaborated",
                "reference_type_key": None,
                "detail": "The type elaborated without a reference equality check.",
            }
        )

    updated = validate_mapping(
        problem,
        elaborates,
        evidence=evidence,
        environment_digest=checked.environment_digest,
    )
    assert updated.status == "needs_review"
    assert updated.status_reason == elaborates(problem, evidence.reference_type).detail

    reviewed_again = validate_mapping(
        problem,
        lambda _problem, _expected: checked,
        evidence=updated,
        environment_digest=checked.environment_digest,
    )
    assert reviewed_again.status == "needs_review"

    with pytest.raises(ValueError, match="requires a checked reference type"):
        MappingEvidence.model_validate(
            updated.model_dump() | {"status": "curated_validated"}
        )


def test_validated_review_requires_each_binder_and_conclusion() -> None:
    corpus = Corpus.open(_MANIFEST)
    evidence = corpus.mapping("ring-add-cancel-pair")
    assumptions = tuple(row for row in evidence.alignment if row.kind == "assumption")
    assert len(assumptions) == 3
    incomplete = tuple(row for row in evidence.alignment if row != assumptions[-1])
    with pytest.raises(ValueError, match="align the full reference type"):
        MappingEvidence.model_validate(
            evidence.model_dump() | {"alignment": incomplete}
        )


@pytest.mark.parametrize("change", ("conclusion", "imports", "source", "environment"))
def test_evidence_is_invalidated_when_identity_changes(change: str) -> None:
    corpus = Corpus.open(_MANIFEST)
    problem = corpus.problems("train")[0]
    evidence = corpus.mapping(problem.task_id)
    checked = evidence.check
    assert checked is not None
    environment = checked.environment_digest
    if change == "conclusion":
        update: dict[str, object] = {"lean_statement": "a = a"}
    elif change == "imports":
        update = {"imports": (*problem.imports, "Mathlib.Algebra.Ring.Defs")}
    elif change == "source":
        update = {"source": problem.source.model_dump() | {"content_digest": "0" * 64}}
    else:
        update = {}
        environment = "0" * 64
    changed = Problem.model_validate(
        problem.model_dump(exclude={"statement_digest"}) | update
    )
    with pytest.raises(
        ValueError, match="evidence does not match|stale mapping environment"
    ):
        validate_mapping(
            changed,
            lambda _problem, _reference: pytest.fail(
                "stale evidence reached Lean checker"
            ),
            evidence=evidence,
            environment_digest=environment,
        )


@pytest.mark.parametrize("status", ("unsupported", "needs_review"))
def test_excluded_task_retains_its_mapping_reason(tmp_path: Path, status: str) -> None:
    data = json.loads(_MANIFEST.read_bytes())
    data["mapping_evidence_path"] = "evidence.json"
    manifest = tmp_path / "elementary.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    mappings = json.loads(_MAPPINGS.read_bytes())
    entry = mappings["mappings"][0]
    entry["status"] = status
    entry["status_reason"] = "The supplied English source requires further review."
    (tmp_path / "evidence.json").write_text(json.dumps(mappings), encoding="utf-8")
    # Preserve the pinned source identity while replacing only this mapping companion.
    for name in ("lean-toolchain", "lake-manifest.json"):
        (tmp_path / name).write_bytes((_ROOT / name).read_bytes())
    for task in data["tasks"]:
        location = task["problem"]["source"]["location"]
        path = tmp_path / location
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((_ROOT / location).read_bytes())
    corpus = Corpus.open(manifest)
    assert entry["task_id"] not in {
        problem.task_id for problem in corpus.problems("train")
    }
    assert corpus.exclusions() == ((entry["task_id"], entry["status_reason"]),)
    with pytest.raises(ValueError, match="requires further review"):
        corpus.allowed_declarations(entry["task_id"])
