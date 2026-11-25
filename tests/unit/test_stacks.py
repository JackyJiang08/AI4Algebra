"""Exercise offline Stacks provenance, selection, and source-identity checks."""

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ai4algebra.corpus import Corpus
from ai4algebra.corpus.stacks import (
    STACKS_REPOSITORY,
    StacksSnapshot,
    import_stacks,
)
from ai4algebra.formalization import MappingEvidence

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / "data/manifests/stacks-pilot.json"
_SNAPSHOT = _ROOT / "data/manifests/stacks-snapshot.json"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "core.autocrlf=false",
            "-c",
            "user.name=Snapshot Fixture",
            "-c",
            "user.email=fixture@example.test",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _commit(repo: Path) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "Synthetic Stacks snapshot")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def pinned_history(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "stacks"
    (repo / "tags").mkdir(parents=True)
    _git(repo, "init", "-q")
    (repo / "COPYING").write_text("Synthetic license fixture.", encoding="utf-8")
    (repo / "introduction.tex").write_text(
        "Synthetic license notice.", encoding="utf-8"
    )
    (repo / "tags/tags").write_text(
        "# example tag map\n04FX,algebra-section-sets\n"
        "04FY,algebra-lemma-basic\n04FZ,more-algebra-lemma-target\n",
        encoding="utf-8",
    )
    (repo / "algebra.tex").write_text(
        r"""\section{Sets}
\label{section-sets}
% \label{lemma-basic}

\begin{lemma}
\label{lemma-basic}
Use Section \ref{section-sets} and Lemma \ref{more-algebra-lemma-target}.
\end{lemma}

\begin{proof}
REFERENCE_PROOF_BYTES. See \ref{more-algebra-lemma-target}. % \ref{fake}
\end{proof}
""",
        encoding="utf-8",
    )
    (repo / "more-algebra.tex").write_text(
        "\\begin{lemma}\n\\label{lemma-target}\nAn auxiliary result.\n\\end{lemma}\n",
        encoding="utf-8",
    )
    return repo, _commit(repo)


def test_uses_pinned_git_objects_and_extracts_citations_without_raw_proofs(
    pinned_history: tuple[Path, str],
) -> None:
    repo, pin = pinned_history
    (repo / "algebra.tex").write_text(
        "Changed outside the selected commit.", encoding="utf-8"
    )
    snapshot = import_stacks(repo, pin, ("04FZ", "04FY", "04FX"))
    assert snapshot.commit == pin and snapshot.repository == STACKS_REPOSITORY
    assert snapshot.license_ref.startswith("GFDL-1.2-or-later")
    assert snapshot.entry("04FX").kind == "section"
    assert snapshot.entry("04FX").statement_digest is None
    assert snapshot.entry("04FZ").source_file == "more-algebra.tex"
    theorem = snapshot.entry("04FY")
    assert theorem.kind == "lemma" and theorem.statement_digest is not None
    assert theorem.start_line == 5 and theorem.end_line == 8
    assert [(ref.tag, ref.scope) for ref in theorem.citations] == [
        ("04FX", "statement"),
        ("04FZ", "statement"),
        ("04FZ", "proof"),
    ]
    assert "REFERENCE_PROOF_BYTES" not in snapshot.to_json()
    assert StacksSnapshot.from_json(snapshot.to_json()) == snapshot
    with pytest.raises(ValueError, match="section, not a theorem"):
        snapshot.source_ref("04FX", "snapshot.json")


def test_reconciles_moved_and_missing_tags(pinned_history: tuple[Path, str]) -> None:
    repo, pin = pinned_history
    old = import_stacks(repo, pin, ("04FY", "04FZ"))
    (repo / "tags/tags").write_text("04FY,more-algebra-lemma-basic\n", encoding="utf-8")
    (repo / "more-algebra.tex").write_text(
        "\\begin{lemma}\n\\label{lemma-basic}\nMoved statement.\n\\end{lemma}\n",
        encoding="utf-8",
    )
    new_pin = _commit(repo)
    new = import_stacks(repo, new_pin, ("04FY",))
    assert [(row.tag, row.change) for row in new.reconcile(old)] == [
        ("04FY", "moved"),
        ("04FZ", "not_in_snapshot"),
    ]
    assert new.source_ref("04FY", "snapshot.json") != old.source_ref(
        "04FY", "snapshot.json"
    )
    with pytest.raises(ValueError, match="missing from the pinned index"):
        import_stacks(repo, new_pin, ("04FZ",))


def test_same_tag_detects_changed_statement_and_rejects_wrong_label(
    pinned_history: tuple[Path, str],
) -> None:
    repo, pin = pinned_history
    old = import_stacks(repo, pin, ("04FZ",))
    chapter = repo / "more-algebra.tex"
    content = chapter.read_text(encoding="utf-8")
    chapter.write_text(
        content.replace("An auxiliary result.", "Different result."), encoding="utf-8"
    )
    new = import_stacks(repo, _commit(repo), ("04FZ",))
    assert new.reconcile(old)[0].change == "statement_changed"
    chapter.write_text(
        content.replace("lemma-target", "lemma-unrelated"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="no unique source label"):
        import_stacks(repo, _commit(repo), ("04FZ",))
    with pytest.raises(ValueError, match="exact local Git commit"):
        import_stacks(repo, "HEAD", ("04FZ",))


def test_importer_sanitizes_local_git_environment(
    pinned_history: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, pin = pinned_history
    monkeypatch.setenv("OpenAI_API_KEY", "synthetic-key-for-environment-test")
    monkeypatch.setenv("GIT_TRACE_CURL", "1")
    native_run = subprocess.run

    def inspect_run(*args: Any, **kwargs: Any) -> Any:
        child_env = kwargs["env"]
        assert not {"openai_api_key", "git_trace_curl"} & {
            key.casefold() for key in child_env
        }
        assert child_env["GIT_NO_LAZY_FETCH"] == "1"
        assert child_env["GIT_TERMINAL_PROMPT"] == "0"
        return native_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", inspect_run)
    snapshot = import_stacks(repo, pin, ("04FY",))
    assert snapshot.entry("04FY").kind == "lemma"


def test_pilot_source_mismatch_and_explicit_subclaim_scope(tmp_path: Path) -> None:
    catalog = Corpus.open(_MANIFEST)
    source_snapshot = StacksSnapshot.from_json(_SNAPSHOT.read_bytes())
    [train] = catalog.problems("train")
    assert train.source == source_snapshot.source_ref("00E5", train.source.location)
    evidence = catalog.mapping(train.task_id)
    assert evidence.source_scope == "subclaim"
    with pytest.raises(ValueError, match="explicit source scope"):
        MappingEvidence.model_validate(
            evidence.model_dump() | {"source_scope_note": None}
        )
    with pytest.raises(ValueError, match="explicit source scope"):
        MappingEvidence.model_validate(evidence.model_dump(exclude={"source_scope"}))
    [validation] = catalog.problems("validation")
    implicit_scope = MappingEvidence.model_validate(
        catalog.mapping(validation.task_id).model_dump(exclude={"source_scope"})
    )
    assert implicit_scope.check is not None
    with pytest.raises(ValueError, match="requires explicit source scope"):
        implicit_scope.bind(validation, implicit_scope.check.environment_digest)
    manifest = json.loads(_MANIFEST.read_bytes())
    changed = tmp_path / "stacks-mismatch.json"
    manifest["tasks"][0]["problem"]["informal_statement"] = "An unrelated assertion."
    changed.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="mapping evidence does not match"):
        Corpus.open(changed, source_root=_ROOT)
    manifest["tasks"][0]["problem"]["source"]["content_digest"] = "0" * 64
    changed.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Stacks source identity mismatch"):
        Corpus.open(changed, source_root=_ROOT)


def test_selection_report_and_upstream_license_match_public_snapshot() -> None:
    corpus = Corpus.open(_MANIFEST)
    snapshot = StacksSnapshot.from_json(_SNAPSHOT.read_bytes())
    report = json.loads((_ROOT / "data/manifests/stacks-selection.json").read_bytes())
    assert report["commit"] == snapshot.commit
    assert set(row["tag"] for row in (*report["selected"], *report["excluded"])) == {
        entry.tag for entry in snapshot.entries
    }
    assert report["counts"] == {
        "considered_tags": len(snapshot.entries),
        "admitted_tasks": len(corpus.problems()),
        "full_tag_mappings": sum(row["scope"] == "full" for row in report["selected"]),
        "subclaim_mappings": sum(
            row["scope"] == "subclaim" for row in report["selected"]
        ),
        "excluded_tags": len(report["excluded"]),
    }
    for row in report["selected"]:
        assert corpus.mapping(row["task_id"]).source_scope == row["scope"]
    license_text = (_ROOT / report["license"]).read_text(encoding="utf-8")
    assert (
        hashlib.sha256(license_text.encode("utf-8")).hexdigest()
        == snapshot.license_digest
    )
    notice = (_ROOT / report["attribution"]).read_text(encoding="utf-8")
    assert snapshot.commit in notice and snapshot.license_notice_source_digest in notice


def test_reproduces_pilot_metadata_from_configured_offline_checkout() -> None:
    checkout = os.environ.get("AI4ALGEBRA_TEST_STACKS_CHECKOUT")
    if not checkout:
        pytest.skip(
            "set AI4ALGEBRA_TEST_STACKS_CHECKOUT to a local Stacks Git checkout"
        )
    saved = StacksSnapshot.from_json(_SNAPSHOT.read_bytes())
    rebuilt = import_stacks(
        Path(checkout), saved.commit, (item.tag for item in saved.entries)
    )
    assert rebuilt == saved
