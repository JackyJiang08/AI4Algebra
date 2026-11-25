"""Source identities and bounded offline extraction from pinned Stacks Git objects."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Iterable
from itertools import islice
from pathlib import Path
from typing import Annotated, Final, Literal, get_args

from pydantic import Field, StringConstraints, model_validator
from typing_extensions import Self

from ai4algebra.contracts import Digest, NonBlank, Record, SourceRef, digest_json

STACKS_REPOSITORY: Final = "https://github.com/stacks/stacks-project"
STACKS_ATTRIBUTION: Final = "The Stacks Project, Johan de Jong and contributors"
STACKS_LICENSE: Final = (
    "GFDL-1.2-or-later (COPYING and introduction.tex at the pinned commit)"
)
STACKS_SOURCE_KIND = "stacks-tag"
_TAG_INDEX = "tags/tags"
_MAX_TAGS = 32
_MAX_FILE_BYTES = 16 * 1024 * 1024
_TAG = re.compile(r"[0-9A-Z]{4}", re.ASCII)
_COMMIT = re.compile(r"[0-9a-f]{40}", re.ASCII)
_CHAPTER = re.compile(r"[a-z0-9-]+\.tex", re.ASCII)
_LABEL = re.compile(r"[A-Za-z0-9_:+.-]+", re.ASCII)
_REFERENCE = re.compile(r"\\(?:ref|eqref|autoref)\s*\{([^{}\s]+)\}")
_COMMENT = re.compile(r"(?<!\\)(?:\\\\)*(%[^\n]*)")
_GIT_ENV = frozenset(
    {
        "path",
        "pathext",
        "systemroot",
        "windir",
        "comspec",
        "tmp",
        "temp",
        "tmpdir",
        "ld_library_path",
    }
)

Tag = Annotated[str, StringConstraints(pattern=r"^[0-9A-Z]{4}$")]
Commit = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
ChapterFile = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]+\.tex$")]
EntryKind = Literal[
    "lemma",
    "theorem",
    "proposition",
    "corollary",
    "definition",
    "remark",
    "example",
    "section",
    "item",
    "other",
]
_LABEL_KINDS: dict[str, EntryKind] = {kind: kind for kind in get_args(EntryKind)}
_ENVIRONMENTS = {
    "lemma",
    "theorem",
    "proposition",
    "corollary",
    "definition",
    "remark",
    "example",
}
THEOREM_KINDS = frozenset({"lemma", "theorem", "proposition", "corollary"})


class Citation(Record):
    label: NonBlank
    tag: Tag | None
    scope: Literal["statement", "proof"]


class StacksEntry(Record):
    tag: Tag
    full_label: NonBlank
    source_file: ChapterFile
    source_file_digest: Digest
    tag_record_digest: Digest
    kind: EntryKind
    start_line: Annotated[int, Field(ge=1)]
    end_line: Annotated[int, Field(ge=1)]
    statement_digest: Digest | None
    citations: tuple[Citation, ...] = ()

    @model_validator(mode="after")
    def _check_fragment(self) -> Self:
        if not self.full_label.startswith(self.source_file.removesuffix(".tex") + "-"):
            raise ValueError("Stacks entry label does not match its source chapter")
        if self.end_line < self.start_line:
            raise ValueError("Stacks fragment has an inverted line range")
        if (self.statement_digest is not None) != (self.kind in _ENVIRONMENTS):
            raise ValueError("Stacks statement digest does not match entry kind")
        if self.statement_digest is None and self.citations:
            raise ValueError("unextracted entry cannot declare citations")
        if self.tag_record_digest != _hash(
            f"{self.tag},{self.full_label}".encode("utf-8")
        ):
            raise ValueError("Stacks tag record digest does not match its label")
        return self


class TagChange(Record):
    tag: Tag
    change: Literal[
        "added", "not_in_snapshot", "moved", "statement_changed", "source_changed"
    ]


class StacksSnapshot(Record):
    """Proof-free metadata for a bounded selection of published Stacks tags."""

    repository: Literal["https://github.com/stacks/stacks-project"] = STACKS_REPOSITORY
    commit: Commit
    attribution: Literal["The Stacks Project, Johan de Jong and contributors"] = (
        STACKS_ATTRIBUTION
    )
    license_ref: Literal[
        "GFDL-1.2-or-later (COPYING and introduction.tex at the pinned commit)"
    ] = STACKS_LICENSE
    tag_index_digest: Digest
    license_digest: Digest
    license_notice_source_digest: Digest
    entries: tuple[StacksEntry, ...]

    @model_validator(mode="after")
    def _check_entries(self) -> Self:
        if not 1 <= len(self.entries) <= _MAX_TAGS:
            raise ValueError("Stacks snapshot selection is empty or exceeds its bound")
        if len({entry.tag for entry in self.entries}) != len(self.entries):
            raise ValueError("duplicate tag in Stacks snapshot")
        if len({entry.full_label for entry in self.entries}) != len(self.entries):
            raise ValueError("duplicate label in Stacks snapshot")
        file_digests: dict[str, str] = {}
        for entry in self.entries:
            if (
                file_digests.setdefault(entry.source_file, entry.source_file_digest)
                != entry.source_file_digest
            ):
                raise ValueError("same Stacks source file has conflicting digests")
        return self

    def entry(self, tag: str) -> StacksEntry:
        for entry in self.entries:
            if entry.tag == tag:
                return entry
        raise ValueError(f"Stacks tag {tag} is missing from the snapshot")

    def source_ref(self, tag: str, location: str) -> SourceRef:
        entry = self.entry(tag)
        if entry.kind not in THEOREM_KINDS:
            raise ValueError(
                f"Stacks tag {tag} identifies a {entry.kind}, not a theorem"
            )
        return SourceRef(
            kind=STACKS_SOURCE_KIND,
            source_id=tag,
            revision=self.commit,
            location=location,
            content_digest=digest_json(
                (
                    self.repository,
                    self.commit,
                    self.tag_index_digest,
                    self.license_digest,
                    self.license_notice_source_digest,
                    entry.model_dump(mode="json"),
                )
            ),
            attribution=self.attribution,
            license_ref=self.license_ref,
        )

    def reconcile(self, previous: StacksSnapshot) -> tuple[TagChange, ...]:
        """Compare selected tag records, including those absent from this selection."""
        old = {entry.tag: entry for entry in previous.entries}
        new = {entry.tag: entry for entry in self.entries}
        changes: list[TagChange] = []
        for tag in sorted(old.keys() | new.keys()):
            if tag not in old:
                changes.append(TagChange(tag=tag, change="added"))
            elif tag not in new:
                changes.append(TagChange(tag=tag, change="not_in_snapshot"))
            elif old[tag].full_label != new[tag].full_label:
                changes.append(TagChange(tag=tag, change="moved"))
            elif old[tag].statement_digest != new[tag].statement_digest:
                changes.append(TagChange(tag=tag, change="statement_changed"))
            elif old[tag] != new[tag]:
                changes.append(TagChange(tag=tag, change="source_changed"))
        return tuple(changes)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(checkout: Path, *args: str) -> bytes:
    inherited = {
        key: value for key, value in os.environ.items() if key.casefold() in _GIT_ENV
    }
    try:
        result = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "-c",
                "protocol.allow=never",
                "-C",
                str(checkout),
                *args,
            ],
            capture_output=True,
            check=True,
            timeout=30,
            env=inherited
            | {
                "GIT_NO_LAZY_FETCH": "1",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(
            f"cannot read pinned local Stacks object for {args[-1]}"
        ) from exc
    return result.stdout


def _blob(checkout: Path, commit: str, filename: str) -> bytes:
    ref = f"{commit}:{filename}"
    size = int(_git(checkout, "cat-file", "-s", ref))
    if size > _MAX_FILE_BYTES:
        raise ValueError(f"Stacks file exceeds the import size bound: {filename}")
    content = _git(checkout, "cat-file", "blob", ref)
    if len(content) != size:
        raise ValueError(f"Stacks file size disagrees with its Git object: {filename}")
    return content


def _index(data: bytes) -> tuple[dict[str, str], dict[str, str]]:
    by_tag = {}
    by_label = {}
    for line in data.decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        tag, separator, label = line.partition(",")
        if not separator or not _TAG.fullmatch(tag) or not _LABEL.fullmatch(label):
            raise ValueError("invalid record in pinned Stacks tag index")
        if tag in by_tag or label in by_label:
            raise ValueError("duplicate tag or label in pinned Stacks tag index")
        by_tag[tag] = label
        by_label[label] = tag
    return by_tag, by_label


def _without_comments(source: str) -> str:
    return _COMMENT.sub(
        lambda match: match[0][: match.start(1) - match.start()] + " " * len(match[1]),
        source,
    )


def _citations(
    text: str,
    *,
    chapter: str,
    labels: dict[str, str],
    scope: Literal["statement", "proof"],
) -> tuple[Citation, ...]:
    return tuple(
        Citation(
            label=label,
            tag=labels.get(f"{chapter}-{label}", labels.get(label)),
            scope=scope,
        )
        for label in dict.fromkeys(_REFERENCE.findall(text))
    )


def _kind(label: str) -> EntryKind:
    return _LABEL_KINDS.get(label.partition("-")[0], "other")


def _entry(
    tag: str, full_label: str, chapter: str, data: bytes, labels: dict[str, str]
) -> StacksEntry:
    original = data.decode("utf-8")
    source = _without_comments(original)
    local_label = full_label[len(chapter) + 1 :]
    locations = list(
        re.finditer(r"\\label\s*\{" + re.escape(local_label) + r"\}", source)
    )
    if len(locations) != 1:
        raise ValueError(f"Stacks tag {tag} has no unique source label {full_label}")
    location = locations[0]
    kind = _kind(local_label)
    start, end = location.span()
    statement_digest = None
    citations: tuple[Citation, ...] = ()
    if kind in _ENVIRONMENTS:
        opening, closing = f"\\begin{{{kind}}}", f"\\end{{{kind}}}"
        start = source.rfind(opening, 0, location.start())
        stop = source.find(closing, location.end())
        if start < 0 or stop < 0 or closing in source[start : location.start()]:
            raise ValueError(
                f"Stacks tag {tag} is outside its expected {kind} environment"
            )
        end = stop + len(closing)
        if opening in source[location.end() : stop]:
            raise ValueError(f"Stacks tag {tag} has a nested {kind} environment")
        statement_digest = _hash(original[start:end].encode("utf-8"))
        citations = _citations(
            source[start:end], chapter=chapter, labels=labels, scope="statement"
        )
        if source[end:].lstrip().startswith(r"\begin{proof}"):
            proof_start = source.index(r"\begin{proof}", end)
            proof_end = source.find(r"\end{proof}", proof_start)
            if proof_end < 0:
                raise ValueError(
                    f"Stacks tag {tag} has an unterminated proof environment"
                )
            citations += _citations(
                source[proof_start:proof_end],
                chapter=chapter,
                labels=labels,
                scope="proof",
            )
    return StacksEntry(
        tag=tag,
        full_label=full_label,
        source_file=f"{chapter}.tex",
        source_file_digest=_hash(data),
        tag_record_digest=_hash(f"{tag},{full_label}".encode("utf-8")),
        kind=kind,
        start_line=source.count("\n", 0, start) + 1,
        end_line=source.count("\n", 0, end) + 1,
        statement_digest=statement_digest,
        citations=citations,
    )


def import_stacks(checkout: Path, commit: str, tags: Iterable[str]) -> StacksSnapshot:
    """Read selected TeX objects at an exact local commit and publish hash metadata."""
    selection = tuple(islice(tags, _MAX_TAGS + 1))
    if (
        not 1 <= len(selection) <= _MAX_TAGS
        or len(set(selection)) != len(selection)
        or any(not _TAG.fullmatch(tag) for tag in selection)
    ):
        raise ValueError(
            "Stacks import requires a bounded selection of unique four-character tags"
        )
    if (
        not _COMMIT.fullmatch(commit)
        or _git(checkout, "cat-file", "-t", commit).strip() != b"commit"
    ):
        raise ValueError("Stacks source requires an exact local Git commit")

    tag_index = _blob(checkout, commit, _TAG_INDEX)
    by_tag, by_label = _index(tag_index)
    filenames = _git(checkout, "ls-tree", "--name-only", "-z", commit).decode("utf-8")
    chapters = sorted(
        (
            name.removesuffix(".tex")
            for name in filenames.split("\0")
            if _CHAPTER.fullmatch(name)
        ),
        key=len,
        reverse=True,
    )
    source: dict[str, bytes] = {}
    entries: list[StacksEntry] = []
    for tag in sorted(selection):
        label = by_tag.get(tag)
        if label is None:
            raise ValueError(f"Stacks tag {tag} is missing from the pinned index")
        chapter = next(
            (name for name in chapters if label.startswith(name + "-")), None
        )
        if chapter is None:
            raise ValueError(f"Stacks tag {tag} does not identify a source chapter")
        if chapter not in source:
            source[chapter] = _blob(checkout, commit, chapter + ".tex")
        entries.append(_entry(tag, label, chapter, source[chapter], by_label))
    return StacksSnapshot(
        commit=commit,
        tag_index_digest=_hash(tag_index),
        license_digest=_hash(_blob(checkout, commit, "COPYING")),
        license_notice_source_digest=_hash(_blob(checkout, commit, "introduction.tex")),
        entries=tuple(entries),
    )
