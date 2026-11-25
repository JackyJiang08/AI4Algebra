"""Validate corpus admission, family splits and the public proof boundary."""

import hashlib
import json
import os
import shutil
from importlib import import_module
from pathlib import Path
from typing import IO, Any, cast

import pytest

from ai4algebra.contracts import Candidate, digest_json
from ai4algebra.corpus import POLICY_BUNDLE_VERSION, Corpus, Manifest, partition_digest
from ai4algebra.lean_bridge.protocol import WorkerRequest

_ROOT = Path(__file__).resolve().parents[2]
_RELATIVE_MANIFEST = Path("data/manifests/elementary.json")
_MANIFEST = _ROOT / _RELATIVE_MANIFEST


def _modified_manifest(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "elementary.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_elementary_catalog_has_stable_families_and_distinct_eligibility() -> None:
    corpus = Corpus.open(_MANIFEST)
    assert [item.task_id for item in corpus.problems("train")] == [
        "group-inverse-identity",
        "group-ordered-inverse",
    ]
    assert [item.task_id for item in corpus.problems("validation")] == [
        "ring-distribute-sub"
    ]
    assert [item.task_id for item in corpus.problems("test")] == [
        "ring-add-cancel-pair"
    ]
    assert (
        partition_digest(reversed(corpus.problems()))
        == corpus.manifest.partition_digest
    )
    assert corpus.exclusions() == ()

    policies = tuple(
        corpus.allowed_declarations(item.task_id) for item in corpus.problems()
    )
    assert len({entry.eligibility_digest for entry in policies}) == 4
    assert {entry.policy_digest for entry in policies} == {corpus.policy_digest}
    assert corpus.policy_digest == digest_json(
        (
            POLICY_BUNDLE_VERSION,
            sorted((policy.task_id, policy.eligibility_digest) for policy in policies),
        )
    )
    first = corpus.problems("train")[0]
    policy = corpus.eligibility_policy(first)
    assert policy == policies[0]
    assert "mul_inv_cancel" in policy.allowed_declarations
    assert "mul_inv_cancel_right" in policy.forbidden_declarations
    assert "mul_div_cancel_right" in policy.forbidden_declarations
    assert set(problem.lean_name for problem in corpus.problems()) <= set(
        policy.forbidden_declarations
    )
    with pytest.raises(ValueError, match="ineligible"):
        policy.validate_for(
            first,
            (Candidate(operation="exact", goal_id="g0", lemma="mul_inv_cancel_right"),),
        )


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ("schema", "unsupported schema version"),
        ("duplicate_id", "duplicate task ID"),
        ("missing_hash", "missing statement_digest"),
        ("split", "validation"),
        ("family", "crosses splits"),
        ("partition", "partition digest"),
        ("proof_field", "Extra inputs"),
    ),
)
def test_invalid_manifest_records_are_rejected(change: str, message: str) -> None:
    data = json.loads(_MANIFEST.read_bytes())
    if change == "schema":
        data["schema_version"] = 2
    elif change == "duplicate_id":
        data["tasks"].append(data["tasks"][0])
    elif change == "missing_hash":
        del data["tasks"][0]["problem"]["statement_digest"]
    elif change == "split":
        data["tasks"][0]["problem"]["split"] = "training"
    elif change == "family":
        data["tasks"][0]["problem"]["split"] = "test"
    elif change == "partition":
        data["partition_digest"] = "0" * 64
    else:
        data["tasks"][0]["gold_proof"] = "by exact target"
    with pytest.raises(ValueError, match=message):
        Manifest.from_json(json.dumps(data))


def test_missing_or_modified_source_is_rejected(tmp_path: Path) -> None:
    shutil.copytree(_ROOT / "data/manifests", tmp_path / "data/manifests")
    (tmp_path / "data/formalizations").mkdir()
    shutil.copyfile(
        _ROOT / "data/formalizations/elementary.json",
        tmp_path / "data/formalizations/elementary.json",
    )
    shutil.copyfile(_ROOT / "lean-toolchain", tmp_path / "lean-toolchain")
    shutil.copyfile(_ROOT / "lake-manifest.json", tmp_path / "lake-manifest.json")
    path = tmp_path / _RELATIVE_MANIFEST
    source = tmp_path / "data/manifests/sources/group-inverse-identity.txt"
    source.write_text("An updated exercise.", encoding="utf-8")
    with pytest.raises(ValueError, match="source digest mismatch"):
        Corpus.open(path)
    source.unlink()
    with pytest.raises(ValueError, match="missing source"):
        Corpus.open(path)


@pytest.mark.parametrize(
    "change", ("alias", "wrapper", "cycle", "gold_import", "gold_source")
)
def test_answers_and_circular_dependencies_are_rejected(
    tmp_path: Path, change: str
) -> None:
    data = json.loads(_MANIFEST.read_bytes())
    task = data["tasks"][0]
    if change == "gold_import":
        problem = task["problem"]
        problem["imports"].append("AI4Algebra.Benchmarks.Gold")
        problem["statement_digest"] = digest_json(
            (
                problem["schema_version"],
                problem["lean_name"],
                problem["imports"],
                problem["universes"],
                problem["binders"],
                problem["lean_statement"],
            )
        )
        message = "nonpublic import"
    elif change == "gold_source":
        task["problem"]["source"]["location"] = "AI4Algebra/Benchmarks/Gold.lean"
        message = "protected proof"
    elif change == "alias":
        task["premises"].append("mul_div_cancel_right")
        message = "forbidden premise"
    else:
        data["declarations"].extend(
            [
                {
                    "schema_version": 1,
                    "name": name,
                    "module": "Mathlib.Algebra.Group.Defs",
                    "family_id": "disguised-answer",
                    "disposition": "premise",
                    "depends_on": [dependency],
                }
                for name, dependency in (
                    ("wrapper", "inner"),
                    (
                        "inner",
                        "wrapper" if change == "cycle" else "mul_inv_cancel_right",
                    ),
                )
            ]
        )
        task["premises"].append("wrapper")
        message = (
            "circular declaration" if change == "cycle" else "forbidden premise wrapper"
        )
    with pytest.raises(ValueError, match=message):
        Corpus.open(_modified_manifest(tmp_path, data), source_root=_ROOT)


def test_source_text_must_match_the_selected_exercise(tmp_path: Path) -> None:
    data = json.loads(_MANIFEST.read_bytes())
    source = data["tasks"][0]["problem"]["source"]
    other_source = _ROOT / "data/manifests/sources/group-ordered-inverse.txt"
    source["location"] = other_source.relative_to(_ROOT).as_posix()
    source["content_digest"] = hashlib.sha256(
        other_source.read_text(encoding="utf-8").encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="informal statement differs"):
        Corpus.open(_modified_manifest(tmp_path, data), source_root=_ROOT)


@pytest.mark.parametrize("slot", ("source", "mapping"))
@pytest.mark.parametrize(
    "path_kind", ("direct", "compiled", "case", "alias", "relocated")
)
def test_catalog_selected_files_cannot_read_protected_proofs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, slot: str, path_kind: str
) -> None:
    root = tmp_path / "catalog"
    data = json.loads(_MANIFEST.read_bytes())
    valid_mapping = root / data["mapping_evidence_path"]
    valid_mapping.parent.mkdir(parents=True)
    shutil.copyfile(_ROOT / data["mapping_evidence_path"], valid_mapping)

    protected = root / "AI4Algebra/Benchmarks/Gold.lean"
    if path_kind == "compiled":
        protected = root / ".lake/build/lib/lean/AI4Algebra/Benchmarks/Gold.olean"
    selected = protected
    if path_kind in {"alias", "relocated"}:
        alternate = root / "alternate"
        selected = alternate / protected.name
        link, target = (
            (alternate, protected.parent)
            if path_kind == "alias"
            else (protected.parent, alternate)
        )
        link.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt":
                # Junctions exercise native path resolution without symlink privileges.
                getattr(import_module("_winapi"), "CreateJunction")(
                    str(target), str(link)
                )
            else:
                link.symlink_to(target, target_is_directory=True)
        except (AttributeError, NotImplementedError, OSError) as exc:
            pytest.skip(f"directory aliases unavailable: {exc}")
    protected.parent.mkdir(parents=True, exist_ok=True)
    protected.write_text("protected reference proof", encoding="utf-8")
    if path_kind == "case":
        selected = root / selected.relative_to(root).as_posix().swapcase()
        if selected != protected:
            pytest.skip("requires Windows path case semantics")

    location = selected.relative_to(root).as_posix()
    if slot == "source":
        data["tasks"][0]["problem"]["source"]["location"] = location
    else:
        data["mapping_evidence_path"] = location
    manifest = _modified_manifest(tmp_path, data)

    real_open = Path.open
    resolved_protected = protected.resolve()

    def record_open(path: Path, *args: Any, **kwargs: Any) -> IO[Any]:
        assert path.resolve() != resolved_protected, (
            "attempted read of protected proof bytes"
        )
        return cast(IO[Any], real_open(path, *args, **kwargs))

    monkeypatch.setattr(Path, "open", record_open)
    with pytest.raises(ValueError, match="protected proof"):
        Corpus.open(manifest, source_root=root)


def test_runtime_corpus_never_reads_or_transmits_gold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_read = Path.read_bytes
    text_read = Path.read_text

    def assert_public(path: Path) -> None:
        assert path.name not in {"Gold.lean", "Gold.olean"}

    def read_bytes(path: Path) -> bytes:
        assert_public(path)
        return raw_read(path)

    def read_text(path: Path, *args: Any, **kwargs: Any) -> str:
        assert_public(path)
        return text_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "read_text", read_text)
    corpus = Corpus.open(_MANIFEST)
    for problem in corpus.problems():
        policy = corpus.eligibility_policy(problem)
        evidence = corpus.mapping(problem.task_id)
        check = evidence.check
        assert check is not None
        request = WorkerRequest(
            request_id="test-request",
            session_id="test-session",
            operation="observe",
            environment_digest=check.environment_digest,
            snapshot_id="0" * 64,
            prefix_digest=digest_json(()),
            statement_digest=problem.statement_digest,
            imports=problem.imports,
            theorem_name=problem.lean_name,
            universes=problem.universes,
            binders=problem.binders,
            statement=problem.lean_statement,
            prefix=(),
        )
        payload = request.to_json()
        assert policy.forbidden_imports == ("AI4Algebra.Benchmarks.Gold",)
        assert "Gold" not in payload
        assert "proof" not in json.loads(payload)
