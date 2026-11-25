"""Load curated tasks, source identities and premise policies."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, model_validator
from typing_extensions import Self

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
from ai4algebra.formalization import MappingBundle, MappingEvidence
from ai4algebra.lean_bridge import environment_digest

from .stacks import STACKS_SOURCE_KIND, StacksSnapshot

if TYPE_CHECKING:
    from ai4algebra.verification import EligibilityPolicy

_PROTECTED_MODULE = "AI4Algebra.Benchmarks.Gold"
_PROTECTED_MODULE_PATH = Path(*_PROTECTED_MODULE.split("."))
_PROTECTED_BUILD_PATH = Path(".lake/build/lib/lean") / _PROTECTED_MODULE_PATH
_PROTECTED_PATHS = (
    _PROTECTED_MODULE_PATH,
    _PROTECTED_MODULE_PATH.with_suffix(".lean"),
    _PROTECTED_BUILD_PATH,
    _PROTECTED_BUILD_PATH.with_suffix(".olean"),
    _PROTECTED_BUILD_PATH.with_suffix(".olean.private"),
    _PROTECTED_BUILD_PATH.with_suffix(".olean.server"),
    _PROTECTED_BUILD_PATH.with_suffix(".ilean"),
)
_SPLITS = ("train", "validation", "test")
POLICY_BUNDLE_VERSION = "ai4algebra-eligibility-bundle-v1"


class Declaration(Record):
    """Proof-dependency edges between declarations tracked by the corpus."""

    name: LeanName
    module: LeanName
    family_id: Identifier
    disposition: Literal["premise", "answer", "quarantined"]
    depends_on: tuple[LeanName, ...]

    @model_validator(mode="after")
    def _check_dependencies(self) -> Self:
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("duplicate declaration dependency")
        return self


class TaskEntry(Record):
    problem: Problem
    category: Identifier
    beginner_description: NonBlank
    expected_proof_steps: Annotated[int, Field(ge=1)]
    definitions: tuple[LeanName, ...]
    premises: tuple[LeanName, ...]


def partition_digest(problems: Iterable[Problem]) -> str:
    """Hash the complete task/family/split assignment independently of row order."""
    return digest_json(sorted((p.task_id, p.family_id, p.split) for p in problems))


class Manifest(Record):
    corpus_id: Identifier
    revision: Identifier
    partition_digest: Digest
    mapping_evidence_path: NonBlank
    declarations: tuple[Declaration, ...]
    tasks: tuple[TaskEntry, ...]

    @model_validator(mode="after")
    def _check_metadata(self) -> Self:
        ids: set[str] = set()
        names: set[str] = set()
        original_sources: set[tuple[str, str, str]] = set()
        family_splits: dict[str, Split] = {}
        for entry in self.tasks:
            p = entry.problem
            if p.task_id in ids:
                raise ValueError(f"duplicate task ID {p.task_id}")
            if p.lean_name in names:
                raise ValueError(f"duplicate target declaration {p.lean_name}")
            source_key = (p.source.kind, p.source.source_id, p.source.revision)
            if source_key in original_sources:
                raise ValueError(f"duplicate source identity for task {p.task_id}")
            if family_splits.setdefault(p.family_id, p.split) != p.split:
                raise ValueError(f"equivalence family {p.family_id} crosses splits")
            ids.add(p.task_id)
            names.add(p.lean_name)
            original_sources.add(source_key)
            if len(set(entry.premises)) != len(entry.premises):
                raise ValueError(f"duplicate premise for task {p.task_id}")
        if not ids:
            raise ValueError("manifest contains no tasks")
        if (
            partition_digest(entry.problem for entry in self.tasks)
            != self.partition_digest
        ):
            raise ValueError("partition digest does not match the task assignments")
        return self


def _public_path(root: Path, location: str) -> Path:
    relative = PureWindowsPath(location)
    if (
        relative.anchor
        or not relative.parts
        or any(part.endswith((".", " ")) or ":" in part for part in relative.parts)
        or any(ord(character) < 32 for character in location)
    ):
        raise ValueError(f"invalid corpus path {location!r}")
    result = root.joinpath(*relative.parts).resolve()
    if not result.is_relative_to(root):
        raise ValueError(f"corpus path escapes the source root: {location}")
    if any(
        result.is_relative_to((root / protected).resolve())
        for protected in _PROTECTED_PATHS
    ):
        raise ValueError(f"protected proof cannot be read as corpus data: {location}")
    return result


def _find_project_root(manifest_path: Path) -> Path:
    for directory in manifest_path.parents:
        if (directory / "lean-toolchain").is_file() and (
            directory / "lake-manifest.json"
        ).is_file():
            return directory
    raise ValueError("corpus manifest is outside a pinned Lean project")


def _validate_source(root: Path, problem: Problem) -> None:
    source = problem.source
    path = _public_path(root, source.location)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"missing source for task {problem.task_id}") from exc
    if source.kind == STACKS_SOURCE_KIND:
        pinned = StacksSnapshot.from_json(text).source_ref(
            source.source_id, source.location
        )
        if pinned != source:
            raise ValueError(
                f"Stacks source identity mismatch for task {problem.task_id}"
            )
        return
    # Read as text so a Git checkout's newline conversion preserves the identity.
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != source.content_digest:
        raise ValueError(f"source digest mismatch for task {problem.task_id}")
    if source.kind == "authored-fixture" and text.strip() != problem.informal_statement:
        raise ValueError(
            f"informal statement differs from source for task {problem.task_id}"
        )


def _dependency_closures(
    declarations: dict[str, Declaration],
) -> dict[str, frozenset[str]]:
    closures: dict[str, frozenset[str]] = {}
    visiting: set[str] = set()

    def closure(name: str) -> frozenset[str]:
        if name in visiting:
            raise ValueError(f"circular declaration dependency at {name}")
        if name not in declarations:
            raise ValueError(f"untracked declaration dependency {name}")
        if name not in closures:
            visiting.add(name)
            dependencies: set[str] = set()
            for other in declarations[name].depends_on:
                dependencies.add(other)
                dependencies.update(closure(other))
            visiting.remove(name)
            closures[name] = frozenset(dependencies)
        return closures[name]

    for declaration in declarations:
        closure(declaration)
    return closures


def _is_gold_module(name: str) -> bool:
    return name == _PROTECTED_MODULE or name.startswith(_PROTECTED_MODULE + ".")


def _is_public_import(name: str) -> bool:
    return any(
        name == root or name.startswith(root + ".")
        for root in ("Init", "Std", "Mathlib")
    )


@dataclass(frozen=True)
class Corpus:
    """A catalog of scored problems, their public evidence and reviewed premises."""

    manifest: Manifest
    _mappings: tuple[MappingEvidence, ...]
    _policies: tuple[EligibilityPolicy, ...]
    policy_digest: str

    @classmethod
    def open(cls, manifest: Path | str, *, source_root: Path | None = None) -> Corpus:
        from ai4algebra.verification import EligibilityPolicy

        manifest_path = Path(manifest).resolve()
        root = (
            _find_project_root(manifest_path)
            if source_root is None
            else source_root.resolve()
        )
        catalog = Manifest.from_json(manifest_path.read_bytes())
        mappings = MappingBundle.from_json(
            _public_path(root, catalog.mapping_evidence_path).read_bytes()
        ).mappings
        evidence_by_id = {mapping.evidence_id: mapping for mapping in mappings}
        if set(evidence_by_id) != {
            entry.problem.mapping_evidence_id for entry in catalog.tasks
        }:
            raise ValueError("manifest and mapping evidence cover different tasks")

        declarations = {
            declaration.name: declaration for declaration in catalog.declarations
        }
        if len(declarations) != len(catalog.declarations):
            raise ValueError("duplicate declaration registry entry")
        closures = _dependency_closures(declarations)
        forbidden = {
            declaration.name
            for declaration in catalog.declarations
            if declaration.disposition != "premise"
            or _is_gold_module(declaration.module)
        }
        type_families: dict[str, str] = {}
        answer_families: dict[str, str] = {}
        for entry in catalog.tasks:
            p = entry.problem
            if any(not _is_public_import(module) for module in p.imports):
                raise ValueError(f"nonpublic import for task {p.task_id}")
            _validate_source(root, p)
            evidence = evidence_by_id[p.mapping_evidence_id]
            evidence.bind(p, environment_digest(root, p.imports))
            if (
                evidence.check is not None
                and evidence.check.reference_type_key is not None
            ):
                key = evidence.check.reference_type_key
                if type_families.setdefault(key, p.family_id) != p.family_id:
                    raise ValueError(
                        "identical Lean reference types use different families"
                    )
            for answer in evidence.answer_declarations:
                if answer_families.setdefault(answer, p.family_id) != p.family_id:
                    raise ValueError(
                        f"equivalent declaration {answer} crosses families"
                    )
                if (
                    answer not in declarations
                    or declarations[answer].disposition != "answer"
                ):
                    raise ValueError(f"answer declaration {answer} must be forbidden")
                if declarations[answer].family_id != p.family_id:
                    raise ValueError(
                        f"answer declaration {answer} has the wrong family"
                    )

        # Reject wrappers regardless of how many intermediate declarations they use.
        forbidden.update(name for name, deps in closures.items() if deps & forbidden)
        for entry in catalog.tasks:
            for premise in entry.premises:
                if premise not in declarations or premise in forbidden:
                    raise ValueError(f"unreviewed or forbidden premise {premise}")
        denied = tuple(sorted(forbidden))
        policies = tuple(
            EligibilityPolicy(
                task_id=entry.problem.task_id,
                statement_digest=entry.problem.statement_digest,
                allowed_imports=entry.problem.imports,
                allowed_declarations=entry.premises,
                forbidden_declarations=denied,
                forbidden_imports=(_PROTECTED_MODULE,),
            )
            for entry in catalog.tasks
            if evidence_by_id[entry.problem.mapping_evidence_id].status
            == "curated_validated"
        )
        bundle_digest = digest_json(
            (
                POLICY_BUNDLE_VERSION,
                sorted(
                    (policy.task_id, policy.eligibility_digest) for policy in policies
                ),
            )
        )
        bundled = tuple(
            EligibilityPolicy.model_validate(
                policy.model_dump(exclude={"policy_digest", "eligibility_digest"})
                | {"bundle_digest": bundle_digest}
            )
            for policy in policies
        )
        return cls(catalog, mappings, bundled, bundle_digest)

    def mapping(self, task_id: str) -> MappingEvidence:
        for evidence in self._mappings:
            if evidence.task_id == task_id:
                return evidence
        raise KeyError(task_id)

    def problems(self, split: Split | None = None) -> tuple[Problem, ...]:
        if split is not None and split not in _SPLITS:
            raise ValueError(f"unknown split {split!r}")
        return tuple(
            entry.problem
            for entry in self.manifest.tasks
            if (split is None or entry.problem.split == split)
            and self.mapping(entry.problem.task_id).status == "curated_validated"
        )

    def exclusions(self) -> tuple[tuple[str, str], ...]:
        """Report the assigned tasks excluded from scoring and their evidence reasons."""
        return tuple(
            (item.task_id, item.status_reason)
            for item in self._mappings
            if item.status != "curated_validated"
        )

    def allowed_declarations(self, task_id: str) -> EligibilityPolicy:
        evidence = self.mapping(task_id)
        if evidence.status != "curated_validated":
            raise ValueError(f"task {task_id} is excluded: {evidence.status_reason}")
        return next(policy for policy in self._policies if policy.task_id == task_id)

    def eligibility_policy(self, task: Problem | str) -> EligibilityPolicy:
        policy = self.allowed_declarations(
            task if isinstance(task, str) else task.task_id
        )
        if isinstance(task, Problem) and task not in self.problems():
            raise ValueError(f"task differs from the catalog for {task.task_id}")
        return policy
