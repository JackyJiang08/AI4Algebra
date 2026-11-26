"""Export source proofs from the repository's reviewed Lean solution sets."""

import re
from hashlib import sha256
from pathlib import Path
from typing import Literal

from ai4algebra.contracts import Digest, Identifier, LeanName, NonBlank, Record
from ai4algebra.corpus import Corpus
from ai4algebra.selected_benchmark import CaseFile

from ._artifacts import RunDirectory

_GOLD = "AI4Algebra/Benchmarks/Gold"
_CORPUS_SOURCES = {
    "elementary": (
        f"{_GOLD}.lean",
        "AI4Algebra.Benchmarks.Gold",
        {
            "group_inverse_identity": "group-inverse-identity",
            "group_ordered_inverse": "group-ordered-inverse",
        },
    ),
    "stacks-pilot": (
        f"{_GOLD}/Stacks.lean",
        "AI4Algebra.Benchmarks.Gold.Stacks",
        {"quotient_spectrum_image": "stacks-00E5-image"},
    ),
}
_SELECTED_SOURCES = {
    "group_cases.json": f"{_GOLD}/SelectedGroups.lean",
    "quadratic_cases.json": f"{_GOLD}/SelectedQuadratic.lean",
}
# The reviewed fixtures use unindented theorem commands and an end-of-line
# value separator, optionally followed by `by`. Keep their proof syntax intact.
_THEOREM = re.compile(
    r"^(?:private )?theorem ([\w']+)\b[^\n]*(?:\n[ \t][^\n]*|\n(?=\n))*", re.M
)
_VALUE = re.compile(r" :=(?= *(?:by[ \t]*)?$)", re.M)


class Solution(Record):
    task_id: Identifier | None
    declaration: LeanName
    proof_line: int
    proof_kind: Literal["tactic", "term"]
    proof_body: NonBlank


class SolutionSource(Record):
    path: NonBlank
    sha256: Digest
    solutions: tuple[Solution, ...]


class SolutionArchive(Record):
    scope: Literal["manifest_train", "selected_development_archive"]
    source_set: Identifier
    partition_digest: Digest | None
    sources: tuple[SolutionSource, ...]


def _read(root: Path, path: str) -> bytes:
    source = root / path
    if source.resolve() != source or not source.is_file():
        raise ValueError(f"expected a regular solution-set source at {path}")
    return source.read_bytes()


def _extract(
    root: Path,
    path: str,
    namespace: str,
    tasks: dict[str, str],
    *,
    include_helpers: bool = False,
) -> SolutionSource:
    content = _read(root, path)
    source = content.decode("utf-8").replace("\r\n", "\n")
    if f"\nnamespace {namespace}\n" not in source:
        raise ValueError(f"solution namespace changed in {path}")
    pending = tasks.copy()
    solutions = []
    for theorem in _THEOREM.finditer(source):
        name = theorem[1]
        helper = theorem[0].startswith("private theorem ")
        if name not in tasks and not (include_helpers and helper):
            continue
        if helper and name in tasks:
            raise ValueError(f"expected a public solution for {name} in {path}")
        if not helper and name not in pending:
            raise ValueError(f"duplicate solution for {name} in {path}")
        task_id = pending.pop(name) if not helper else None
        value = _VALUE.search(theorem[0])
        body = "" if value is None else theorem[0][value.end() :].rstrip()
        if value is None or not body.strip():
            raise ValueError(f"unsupported solution layout for {name} in {path}")
        start = theorem.start() + value.end()
        kind: Literal["tactic", "term"] = (
            "tactic" if body.lstrip().split(maxsplit=1)[0] == "by" else "term"
        )
        solutions.append(
            Solution(
                task_id=task_id,
                declaration=f"{namespace}.{name}",
                proof_line=source.count("\n", 0, start + len(body) - len(body.lstrip()))
                + 1,
                proof_kind=kind,
                proof_body=body,
            )
        )
    if pending:
        raise ValueError(f"missing solutions in {path}: {', '.join(sorted(pending))}")
    return SolutionSource(
        path=path, sha256=sha256(content).hexdigest(), solutions=tuple(solutions)
    )


def export_solutions(
    root: Path, corpus: Corpus, directory: RunDirectory, *, include_selected: bool
) -> tuple[str, ...]:
    """Write inspection artifacts. Training and search have no reader for them."""
    root = root.resolve()
    corpus_id = corpus.manifest.corpus_id
    if corpus_id not in _CORPUS_SOURCES:
        raise ValueError(f"no reviewed solution set for corpus {corpus_id}")
    file, namespace, reviewed = _CORPUS_SOURCES[corpus_id]
    tasks = {
        problem.lean_name.rsplit(".", 1)[-1]: problem.task_id
        for problem in corpus.problems("train")
    }
    if not tasks:
        raise ValueError("there are no validated training solutions to export")
    if any(reviewed.get(name) != task_id for name, task_id in tasks.items()):
        raise ValueError(
            "manifest training tasks do not match the reviewed solution set"
        )
    archives = {
        f"{corpus_id}-tactics.json": SolutionArchive(
            scope="manifest_train",
            source_set=corpus_id,
            partition_digest=corpus.manifest.partition_digest,
            sources=(_extract(root, file, namespace, tasks),),
        )
    }
    if include_selected:
        namespace = "AI4Algebra.Benchmarks.Gold.Selected"
        selected = []
        seen_ids: set[str] = set()
        for manifest, path in _SELECTED_SOURCES.items():
            cases = CaseFile.from_json(_read(root, f"data/selected/{manifest}"))
            tasks = {}
            for case in cases.cases:
                prefix, name = case.reference_declaration.rsplit(".", 1)
                if (
                    case.reference_file != path
                    or prefix != namespace
                    or name in tasks
                    or case.id in seen_ids
                ):
                    raise ValueError(f"unexpected selected reference in {manifest}")
                tasks[name] = case.id
                seen_ids.add(case.id)
            selected.append(
                _extract(root, path, namespace, tasks, include_helpers=True)
            )
        archives["selected-development-tactics.json"] = SolutionArchive(
            scope="selected_development_archive",
            source_set="selected-exercises",
            partition_digest=None,
            sources=tuple(selected),
        )
    with directory.writer():
        for filename, archive in archives.items():
            directory.put(filename, archive)
    return tuple(archives)
