"""Run identities and atomic, content-checked experiment artifacts."""

import hashlib
import json
import os
import sqlite3
import subprocess
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import field_validator

from ai4algebra.candidates import (
    ASTRA_STANDARD,
    GENERATOR_VERSION,
    PremiseIndex,
    elementary_premise_index,
)
from ai4algebra.config import RunConfig
from ai4algebra.contracts import (
    Digest,
    Identifier,
    LeanName,
    NonBlank,
    Problem,
    Record,
    Split,
    digest_json,
)
from ai4algebra.corpus import Corpus
from ai4algebra.formalization.stacks_premises import stacks_premise_index
from ai4algebra.lean_bridge import environment_digest
from ai4algebra.lean_bridge.protocol import LEAN_VERSION, MATHLIB_REVISION
from ai4algebra.search import SearchReport, stuck_report


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_hash(path: Path) -> str:
    return _sha256(path.read_text(encoding="utf-8").encode("utf-8"))


_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


_INDEX_BUILDERS: Mapping[str, Callable[[Corpus, Problem, Path], PremiseIndex]] = {
    "elementary": elementary_premise_index,
    "stacks-pilot": stacks_premise_index,
}


def premise_index(corpus: Corpus, problem: Problem, root: Path) -> PremiseIndex:
    builder = _INDEX_BUILDERS.get(corpus.manifest.corpus_id)
    if builder is None:
        raise ValueError(
            f"no reviewed premise index for corpus {corpus.manifest.corpus_id}"
        )
    return builder(corpus, problem, root)


class TaskIdentity(Record):
    task_id: Identifier
    family_id: Identifier
    split: Split
    source_digest: Digest
    statement_digest: Digest
    environment_digest: Digest
    eligibility_digest: Digest | None
    imports: tuple[LeanName, ...]
    exclusion_reason: NonBlank | None
    source_scope: Literal["full", "subclaim"]
    source_scope_note: NonBlank | None


class CatalogIdentity(Record):
    corpus_id: Identifier
    revision: Identifier
    corpus_digest: Digest
    source_digest: Digest
    partition_digest: Digest
    policy_digest: Digest
    generator_version: Identifier
    generator_digest: Digest
    lean_version: NonBlank
    mathlib_revision: Identifier
    tasks: tuple[TaskIdentity, ...]

    @classmethod
    def capture(cls, corpus: Corpus, root: Path) -> "CatalogIdentity":
        exclusions = dict(corpus.exclusions())
        tasks = []
        signatures = []
        for item in sorted(
            corpus.manifest.tasks, key=lambda entry: entry.problem.task_id
        ):
            problem = item.problem
            mapping = corpus.mapping(problem.task_id)
            reason = exclusions.get(problem.task_id)
            eligibility = None
            if reason is None:
                eligibility = corpus.eligibility_policy(problem).eligibility_digest
                index = premise_index(corpus, problem, root)
                signatures.append((problem.task_id, index.model_dump(mode="json")))
            tasks.append(
                TaskIdentity(
                    task_id=problem.task_id,
                    family_id=problem.family_id,
                    split=problem.split,
                    source_digest=problem.source.content_digest,
                    statement_digest=problem.statement_digest,
                    environment_digest=environment_digest(root, problem.imports),
                    eligibility_digest=eligibility,
                    imports=problem.imports,
                    exclusion_reason=reason,
                    source_scope=mapping.source_scope,
                    source_scope_note=mapping.source_scope_note,
                )
            )
        generator_sources = [
            (path.relative_to(_PACKAGE_ROOT).as_posix(), _source_hash(path))
            for path in sorted((_PACKAGE_ROOT / "candidates").rglob("*.py"))
        ]
        return cls(
            corpus_id=corpus.manifest.corpus_id,
            revision=corpus.manifest.revision,
            corpus_digest=digest_json(corpus.manifest.model_dump(mode="json")),
            source_digest=digest_json(
                tuple(
                    (item.problem.task_id, item.problem.source.model_dump(mode="json"))
                    for item in sorted(
                        corpus.manifest.tasks, key=lambda entry: entry.problem.task_id
                    )
                )
            ),
            partition_digest=corpus.manifest.partition_digest,
            policy_digest=corpus.policy_digest,
            generator_version=GENERATOR_VERSION,
            generator_digest=digest_json(
                (GENERATOR_VERSION, generator_sources, signatures)
            ),
            lean_version=LEAN_VERSION,
            mathlib_revision=MATHLIB_REVISION,
            tasks=tuple(tasks),
        )


def _revision(root: Path) -> str | None:
    system_variables = {
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "WINDIR",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in system_variables
    }
    try:
        result = subprocess.run(
            ("git", "rev-parse", "--verify", "HEAD"),
            cwd=root,
            capture_output=True,
            check=True,
            timeout=2.0,
            text=True,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


class RunIdentity(Record):
    run_id: Identifier
    catalog: CatalogIdentity
    config: RunConfig
    code_revision: NonBlank | None
    code_digest: Digest
    price_digest: Digest | None

    @classmethod
    def capture(
        cls, run_id: str, catalog: CatalogIdentity, config: RunConfig, root: Path
    ) -> "RunIdentity":
        python_sources = [
            (path.relative_to(_PACKAGE_ROOT).as_posix(), _source_hash(path))
            for path in sorted(_PACKAGE_ROOT.rglob("*.py"))
        ]
        lean_sources = [
            (name, _source_hash(root / name))
            for name in (
                "AI4Algebra/Bridge/Main.lean",
                "AI4Algebra/Verification/Main.lean",
                "AI4Algebra/Verification/Audit.lean",
                "AI4Algebra/Verification/Replay.lean",
                "lakefile.toml",
            )
        ]
        return cls(
            run_id=run_id,
            catalog=catalog,
            config=RunConfig.from_json(config.to_json()),
            code_revision=_revision(root),
            code_digest=digest_json((python_sources, lean_sources)),
            price_digest=ASTRA_STANDARD.digest if config.paid_enabled else None,
        )


class ArtifactRef(Record):
    path: NonBlank
    sha256: Digest

    @field_validator("path")
    @classmethod
    def _relative(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or ":" in value
            or "\\" in value
        ):
            raise ValueError("artifact path must be a safe relative path")
        return value


class ProofFiles(Record):
    proof: ArtifactRef
    certificate: ArtifactRef
    verdict: ArtifactRef
    lean_replay_command: tuple[str, ...]


class SearchFiles(Record):
    trace: ArtifactRef
    proof: ProofFiles | None
    stuck: ArtifactRef | None = None


@dataclass(frozen=True)
class RunDirectory:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.resolve())

    @property
    def default_run_id(self) -> str:
        return "run-" + digest_json(str(self.root))[:16]

    def path(self, name: str) -> Path:
        ArtifactRef._relative(name)
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("artifact escapes run directory")
        return path

    def put(self, name: str, value: Record | str) -> ArtifactRef:
        text = value if isinstance(value, str) else value.to_json()
        data = text.encode("utf-8")
        path = self.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return ArtifactRef(path=name, sha256=_sha256(data))

    def ref(self, name: str) -> ArtifactRef:
        return ArtifactRef(path=name, sha256=_sha256(self.path(name).read_bytes()))

    def read(self, reference: ArtifactRef) -> bytes:
        payload = self.path(reference.path).read_bytes()
        if _sha256(payload) != reference.sha256:
            raise ValueError(f"artifact digest mismatch at {reference.path}")
        return payload

    @contextmanager
    def writer(self, *, wait_seconds: float = 0.0) -> Iterator[None]:
        """Keep one process in charge of artifacts until a run finishes or exits."""
        self.root.mkdir(parents=True, exist_ok=True)
        # This lock database is separate from the ledger used during paid requests.
        with closing(
            sqlite3.connect(self.path(".run-writer.sqlite"), timeout=wait_seconds)
        ) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc):
                    raise ValueError(
                        "another process is writing this run output"
                    ) from None
                raise
            yield

    def plan(self, record: Record) -> ArtifactRef:
        with self.writer(wait_seconds=2.0):
            return self._plan(record)

    def _plan(self, record: Record) -> ArtifactRef:
        data = record.to_json().encode("utf-8")
        path = self.path("run.json")
        if not path.exists():
            return self.put("run.json", record)
        if path.read_bytes() != data:
            raise ValueError("output already belongs to a different run plan")
        return ArtifactRef(path="run.json", sha256=_sha256(data))

    def archive_search(self, prefix: str, report: SearchReport) -> SearchFiles:
        trace = self.put(f"{prefix}/search.json", report)
        proof = None
        stuck = None
        if report.certificate is not None and report.verdict is not None:
            source = self.put(f"{prefix}/proof.lean", report.certificate.proof)
            proof = ProofFiles(
                proof=source,
                certificate=self.put(f"{prefix}/certificate.json", report.certificate),
                verdict=self.put(f"{prefix}/verdict.json", report.verdict),
                lean_replay_command=(
                    "lake",
                    "env",
                    "lean",
                    "--threads=1",
                    str(self.path(source.path)),
                ),
            )
        else:
            stuck = self.put(
                f"{prefix}/stuck.json",
                json.dumps(
                    stuck_report(report.problem, report), indent=2, ensure_ascii=False
                )
                + "\n",
            )
        return SearchFiles(trace=trace, proof=proof, stuck=stuck)
