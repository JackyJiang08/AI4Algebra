"""Run structural Lean search on the user-selected training exercises offline."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ai4algebra.candidates import CandidateGenerator
from ai4algebra.config import Limits
from ai4algebra.contracts import (
    LeanName,
    NonBlank,
    Problem,
    Record,
    SourceRef,
    digest_json,
)
from ai4algebra.lean_bridge import BridgeError, LeanBridge
from ai4algebra.lean_bridge.protocol import (
    LEAN_BUILD_COMMIT,
    LEAN_VERSION,
    MATHLIB_REVISION,
)
from ai4algebra.search import SearchOptions, SearchReport, solve
from ai4algebra.verification import EligibilityPolicy, Verifier

_SOURCE = Path("data/training_questions.md")
_DEFINITIONS = "AI4Algebra.Benchmarks.SelectedDefinitions"
_DEFINITION_SOURCE = Path(*_DEFINITIONS.split(".")).with_suffix(".lean")
_DEFINITION_OLEAN = Path(".lake/build/lib/lean") / _DEFINITION_SOURCE.with_suffix(
    ".olean"
)
_GOLD = "AI4Algebra.Benchmarks.Gold"
_PUBLIC_IMPORTS = frozenset(
    {
        _DEFINITIONS,
        "Mathlib.Algebra.BigOperators.Group.List.Defs",
        "Mathlib.Algebra.Group.Basic",
        "Mathlib.Algebra.Group.Subgroup.Defs",
        "Mathlib.Data.ZMod.Basic",
        "Mathlib.GroupTheory.OrderOfElement",
        "Mathlib.NumberTheory.Real.Irrational",
    }
)
_CASE_FILES = (
    Path("data/selected/group_cases.json"),
    Path("data/selected/quadratic_cases.json"),
)
_TASK_ID = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_RUN_ID = r"[a-zA-Z0-9]+(?:[._-][a-zA-Z0-9]+)*"
_ATTEMPT = "attempt-001"
_HEADING = re.compile(r"^## \d+\. Exercise (\d+)\b[^\n]*\n", re.MULTILINE)
_LIMITS = Limits(max_steps=4, max_depth=4, max_nodes=4, max_candidates=8)
_OPTIONS = SearchOptions(stop_on_closure=True)


class SelectedCase(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    id: Annotated[str, StringConstraints(pattern=f"^{_TASK_ID}$")]
    exercise: Annotated[int, Field(gt=0)]
    title: NonBlank
    imports: tuple[LeanName, ...]
    universes: tuple[LeanName, ...]
    binders: tuple[NonBlank, ...]
    conclusion: NonBlank
    reference_declaration: LeanName
    reference_file: NonBlank
    reference_imports: tuple[LeanName, ...] = ()
    mapping_note: NonBlank
    forbidden_declarations: tuple[LeanName, ...]
    basic_premises: tuple[LeanName, ...]

    @field_validator("imports")
    @classmethod
    def _review_imports(cls, imports: tuple[str, ...]) -> tuple[str, ...]:
        if denied := set(imports) - _PUBLIC_IMPORTS:
            raise ValueError(f"unapproved selected-exercise import {min(denied)}")
        return imports

    @field_validator("reference_declaration")
    @classmethod
    def _protect_reference(cls, name: str) -> str:
        if not name.startswith(f"{_GOLD}."):
            raise ValueError(
                "reference declarations must be in the protected Gold namespace"
            )
        return name


class CaseFile(Record):
    cases: Annotated[tuple[SelectedCase, ...], Field(min_length=1)]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _source_sections(source: bytes) -> dict[int, str]:
    sections = _HEADING.split(source.decode("utf-8").replace("\r\n", "\n"))
    result = {}
    for number, body in zip(sections[1::2], sections[2::2], strict=True):
        exercise = int(number)
        if exercise in result:
            raise ValueError(f"duplicate exercise {exercise} in {_SOURCE.as_posix()}")
        result[exercise] = body.strip()
    return result


def _problem(case: SelectedCase, source_hash: str, statement: str) -> Problem:
    return Problem(
        task_id=case.id,
        source=SourceRef(
            kind="user_selected_exercise",
            source_id=f"exercise-{case.exercise}",
            revision=source_hash,
            location=_SOURCE.as_posix(),
            content_digest=source_hash,
            attribution="User-selected group theory exercises",
            license_ref="Original textbook and license unspecified",
        ),
        informal_statement=statement,
        family_id=f"selected-exercise-{case.exercise}",
        split="train",
        imports=case.imports,
        lean_name=f"AI4Algebra.Benchmarks.SelectedAttempt.{case.id.replace('-', '_')}",
        universes=case.universes,
        binders=case.binders,
        lean_statement=case.conclusion,
        mapping_evidence_id=f"selected-mapping-{case.exercise}",
    )


def _search(
    root: Path,
    problem: Problem,
    eligibility: EligibilityPolicy,
    limits: Limits,
    episode_id: str,
) -> SearchReport:
    if _DEFINITIONS in problem.imports:
        if (root / _DEFINITION_OLEAN).stat().st_mtime_ns < (
            root / _DEFINITION_SOURCE
        ).stat().st_mtime_ns:
            raise BridgeError(
                f"public definitions are stale; run lake build +{_DEFINITIONS}"
            )
    bridge = LeanBridge(root, approved_imports=_PUBLIC_IMPORTS)
    return solve(
        problem,
        eligibility,
        bridge,
        CandidateGenerator(problem, eligibility, bridge),
        Verifier(root, timeout_seconds=limits.step_timeout_seconds),
        limits,
        mode="deterministic",
        options=_OPTIONS,
        episode_id=episode_id,
    )


def _runtime_files(root: Path) -> dict[str, str]:
    paths = (
        *sorted((root / "src/ai4algebra").rglob("*.py")),
        *sorted((root / "AI4Algebra/Bridge").glob("*.lean")),
        *sorted((root / "AI4Algebra/Verification").glob("*.lean")),
        *(
            root / path
            for path in ("lean-toolchain", "lakefile.toml", "lake-manifest.json")
        ),
    )
    files = {
        path.relative_to(root).as_posix(): _sha256(path.read_bytes()) for path in paths
    }
    for relative in (_DEFINITION_SOURCE, _DEFINITION_OLEAN):
        path = root / relative
        if path.is_file():
            files[relative.as_posix()] = _sha256(path.read_bytes())
    return files


def _statement(problem: Problem) -> str:
    universes = f".{{{', '.join(problem.universes)}}}" if problem.universes else ""
    binders = "".join(f" {binder}" for binder in problem.binders)
    lines = (
        f"theorem {problem.lean_name}{universes}{binders} : ({problem.lean_statement})"
    ).splitlines()
    imports = [f"import {module}" for module in problem.imports]
    return "\n".join(
        (
            *imports,
            "",
            "set_option autoImplicit false",
            "",
            *(f"-- {line}" for line in lines),
            "",
        )
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


def _save_json(path: Path, value: object) -> None:
    temp = path.with_suffix(".json.tmp")
    temp.write_bytes(_json(value).encode("utf-8"))
    temp.replace(path)


def _diagnostics(report: SearchReport | None, error: str | None) -> tuple[str, ...]:
    if report is not None:
        return report.diagnostics
    return (error,) if error else ()


def _attempt_steps(report: SearchReport) -> dict[str, object]:
    return {
        "selected_actions": [
            {
                "parent_node": attempt.node_id,
                "candidate": attempt.candidate.model_dump(mode="json"),
                "outcome": attempt.outcome,
                "child_node": attempt.child_id,
            }
            for attempt in report.attempts
        ],
        "applicability_probes": [
            {
                "parent_node": generation.node_id,
                "candidate": candidate.model_dump(mode="json"),
                "outcome": probe.status,
            }
            for generation in report.generations
            for candidate, probe in zip(
                generation.candidate_set.candidates, generation.probes, strict=True
            )
            if not probe.reused
            and probe.status not in {"not_probed", "already_attempted"}
        ],
    }


def _archive(
    directory: Path,
    original: Path,
    case: SelectedCase,
    problem: Problem,
    eligibility: EligibilityPolicy,
    run_id: str,
    command: tuple[str, ...],
    report: SearchReport | None,
    error: str | None,
    source_section: str,
    *,
    interrupted: bool = False,
) -> dict[str, object]:
    status = report.status if report is not None else "infrastructure_error"
    reason = (
        report.reason
        if report is not None
        else "interrupted"
        if interrupted
        else "execution_failed"
    )
    diagnostics = _diagnostics(report, error)
    initial_goal_observed = None if report is None else bool(report.nodes)
    failure_phase: str | None = "unknown"
    if status == "verified":
        failure_phase = None
    elif initial_goal_observed is not None:
        failure_phase = (
            "search_or_audit" if initial_goal_observed else "initial_observation"
        )
    result: dict[str, object] = {
        "task_id": problem.task_id,
        "exercise": case.exercise,
        "title": case.title,
        "split": problem.split,
        "status": status,
        "reason": reason,
        "initial_goal_observed": initial_goal_observed,
        "failure_phase": failure_phase,
        "diagnostics": diagnostics,
        "budget_reasons": report.budget_reasons if report is not None else (),
        "statement_digest": problem.statement_digest,
        "environment_digest": report.nodes[0].observation.snapshot.environment_digest
        if initial_goal_observed and report is not None
        else None,
        "search_work": report.work.model_dump(mode="json")
        if report is not None
        else None,
        "run_artifacts": original.as_posix(),
        "archive": directory.as_posix(),
    }
    problem_md = (
        f"# Exercise {case.exercise} — {case.title}\n\n"
        f"Task `{problem.task_id}`. Split `{problem.split}`. "
        f"Source `{problem.source.location}` (SHA-256 `{problem.source.content_digest}`).\n\n"
        f"{source_section}\n\n"
        f"Lean mapping: {case.mapping_note}\n"
    )
    detail = (
        "Independent Lean replay accepted the proof, original type, axioms and dependency audit."
        if status == "verified"
        else "No independently verified proof was produced. This outcome does not establish that the statement is false."
    )
    if report is None:
        detail += " Proof search returned no trace, so proof and action evidence are unavailable."
    elif all(attempt.certificate is None for attempt in report.attempts):
        detail += " No complete Lean proof was generated."
    observation_status = (
        "unknown"
        if initial_goal_observed is None
        else str(initial_goal_observed).lower()
    )
    outcome = (
        f"# Exercise {case.exercise} attempt\n\n"
        f"Outcome **{status}** (`{reason}`). {detail}\n\n"
        f"Initial Lean goal observed: {observation_status}.\n"
        f"Run `{run_id}`, attempt `{_ATTEMPT}`, finished {_timestamp()}.\n\n"
        f"Lean `{LEAN_VERSION}` (`{LEAN_BUILD_COMMIT}`) and Mathlib `{MATHLIB_REVISION}`.\n"
        f"Original artifacts `{original.as_posix()}`. See its run's `run.json` for frozen inputs and limits.\n\n"
        f"Diagnostics: {json.dumps(diagnostics, ensure_ascii=False)}\n\n"
        "Offline reproduction argument vector (from the same project root, with a fresh output directory):\n\n"
        f"```json\n{_json(command)}```\n"
    )
    evidence = {
        "problem.md": problem_md,
        "problem.json": problem.to_json(),
        "eligibility.json": eligibility.to_json(),
        "statement.lean": _statement(problem),
        "outcome.md": outcome,
        "outcome.json": _json(result),
    }
    if report is not None:
        evidence["search.json"] = report.to_json()
        if report.certificate is not None and report.verdict is not None:
            evidence["proof.lean"] = report.certificate.proof
            evidence["certificate.json"] = report.certificate.to_json()
            evidence["verdict.json"] = report.verdict.to_json()
        else:
            evidence["attempted-steps.json"] = _json(_attempt_steps(report))
    else:
        evidence["attempted-steps.json"] = _json(
            {"error": error, "selected_actions": None, "applicability_probes": None}
        )

    for destination in (original, directory):
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(f"attempt already exists: {destination}")
        with TemporaryDirectory(dir=destination.parent, prefix=".attempt-") as folder:
            staged = Path(folder)
            for name, content in evidence.items():
                (staged / name).write_bytes(content.encode("utf-8"))
            staged.rename(destination)
    return result


def _reproduction(
    output: Path, records: Path, case_files: Sequence[Path], limits: Limits, task: str
) -> tuple[str, ...]:
    return (
        "python",
        "-m",
        "ai4algebra.selected_benchmark",
        "--output",
        str(output.with_name(f"{output.name}-{task}-replay")),
        "--records",
        str(records),
        *(arg for path in case_files for arg in ("--case-file", str(path))),
        "--task",
        task,
        "--max-steps",
        str(limits.max_steps),
        "--max-depth",
        str(limits.max_depth),
        "--max-nodes",
        str(limits.max_nodes),
        "--max-candidates",
        str(limits.max_candidates),
        "--step-timeout-seconds",
        str(limits.step_timeout_seconds),
        "--task-timeout-seconds",
        str(limits.task_timeout_seconds),
    )


def run_selected(
    root: Path,
    output: Path,
    records: Path,
    case_files: Sequence[Path],
    limits: Limits = _LIMITS,
    *,
    task: str | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    """Freeze public inputs, attempt each requested goal, and persist evidence before moving on."""
    root = root.resolve()
    run_id = output.name if run_id is None else run_id
    if re.fullmatch(_RUN_ID, run_id) is None:
        raise ValueError("run ID must be a portable directory name")
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    for branch in ("succeeded", "failed"):
        if (records / branch / run_id).exists():
            raise FileExistsError(f"attempts already exist for run ID {run_id}")

    source = (root / _SOURCE).read_bytes()
    source_hash = _sha256(source)
    source_sections = _source_sections(source)
    case_digests = {}
    cases: list[SelectedCase] = []
    for path in case_files:
        content = path.read_bytes()
        cases.extend(CaseFile.from_json(content).cases)
        case_digests[path.as_posix()] = _sha256(content)
    if not cases:
        raise ValueError("no selected-exercise cases")
    if len({case.id for case in cases}) != len(cases) or len(
        {case.exercise for case in cases}
    ) != len(cases):
        raise ValueError("duplicate task ID or exercise number across case files")
    exercises = {case.exercise for case in cases}
    if unknown := exercises - source_sections.keys():
        raise ValueError(f"exercise {min(unknown)} is absent from {_SOURCE.as_posix()}")
    if missing := source_sections.keys() - exercises:
        raise ValueError(f"exercise {min(missing)} has no reviewed Lean case")
    positions = {
        exercise: position for position, exercise in enumerate(source_sections)
    }
    selected = sorted(
        (case for case in cases if task is None or case.id == task),
        key=lambda case: positions[case.exercise],
    )
    if not selected:
        raise ValueError(f"unknown selected task {task}")

    forbidden = tuple(
        sorted(
            {
                name
                for case in cases
                for name in (case.reference_declaration, *case.forbidden_declarations)
            }
        )
    )
    problems = [
        (
            _problem(
                case,
                source_hash,
                source_sections[case.exercise]
                .split("**Value:**", maxsplit=1)[0]
                .strip(),
            ),
            case,
        )
        for case in selected
    ]
    files = _runtime_files(root)
    started_at = _timestamp()
    metadata = {
        "schema_version": 1,
        "run_id": run_id,
        "started_at": started_at,
        "split": "train",
        "scope": "User-selected exercises outside the training corpus pending review",
        "mode": "deterministic",
        "candidate_operations": [
            "intro",
            "constructor",
            "exact_local",
            "assumption",
            "reflexivity",
        ],
        "premise_mode": "structural_only",
        "basic_premises_used": False,
        "reference_proof_mode": "not_executed_by_this_runner",
        "application_api": {
            "provider_requests": 0,
            "token_count_requests": 0,
            "settled_usd": "0",
            "outstanding_usd": "0",
        },
        "limits": limits.model_dump(mode="json"),
        "search_options": _OPTIONS.model_dump(mode="json"),
        "source": {"path": _SOURCE.as_posix(), "sha256": source_hash},
        "case_files": case_digests,
        "task_ids": [problem.task_id for problem, _ in problems],
        "code_digest": digest_json(files),
        "runtime_file_sha256": files,
        "python_version": platform.python_version(),
        "lean_version": LEAN_VERSION,
        "lean_build_commit": LEAN_BUILD_COMMIT,
        "mathlib_revision": MATHLIB_REVISION,
    }
    claim = records / ".locks" / run_id
    try:
        claim.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise FileExistsError(f"run ID already claimed: {run_id}") from exc
    output.mkdir(parents=True, exist_ok=False)
    _save_json(output / "run.json", metadata)
    results: list[dict[str, object]] = []

    def save_summary() -> dict[str, object]:
        summary = {
            **metadata,
            "selected_count": len(problems),
            "attempted_count": len(results),
            "completed": len(results) == len(problems)
            and not any(result["reason"] == "interrupted" for result in results),
            "updated_at": _timestamp(),
            "status_counts": dict(Counter(str(result["status"]) for result in results)),
            "initial_observation_failures": sum(
                result["initial_goal_observed"] is False for result in results
            ),
            "results": results,
        }
        _save_json(output / "summary.json", summary)
        return summary

    summary = save_summary()
    for problem, case in problems:
        eligibility = EligibilityPolicy(
            task_id=problem.task_id,
            statement_digest=problem.statement_digest,
            allowed_imports=problem.imports,
            forbidden_declarations=forbidden,
            forbidden_imports=(_GOLD,),
        )
        print(f"Exercise {case.exercise} [{problem.task_id}] searching", flush=True)
        report = None
        error = None
        interrupted = False
        try:
            report = _search(root, problem, eligibility, limits, f"{run_id}-{case.id}")
        except (BridgeError, OSError, ValueError) as exc:
            error = f"{type(exc).__name__}: {exc}"
        except KeyboardInterrupt:
            error = "Interrupted before the proof search returned a trace"
            interrupted = True
        relative = Path(case.id) / _ATTEMPT
        branch = (
            "succeeded"
            if report is not None and report.status == "verified"
            else "failed"
        )
        result = _archive(
            records / branch / run_id / relative,
            output / "tasks" / relative,
            case,
            problem,
            eligibility,
            run_id,
            _reproduction(output, records, case_files, limits, case.id),
            report,
            error,
            source_sections[case.exercise],
            interrupted=interrupted,
        )
        results.append(result)
        summary = save_summary()
        print(
            f"Exercise {case.exercise} [{problem.task_id}] {result['status']} ({result['reason']})",
            flush=True,
        )
        if interrupted:
            raise KeyboardInterrupt
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--records", type=Path, default=Path("records"))
    parser.add_argument(
        "--case-file",
        type=Path,
        action="append",
        help="path to a reviewed case file; specify both reviewed files when overriding the defaults",
    )
    parser.add_argument("--task")
    parser.add_argument("--run-id")
    parser.add_argument("--max-steps", type=int, default=_LIMITS.max_steps)
    parser.add_argument("--max-depth", type=int, default=_LIMITS.max_depth)
    parser.add_argument("--max-nodes", type=int, default=_LIMITS.max_nodes)
    parser.add_argument("--max-candidates", type=int, default=_LIMITS.max_candidates)
    parser.add_argument(
        "--step-timeout-seconds", type=float, default=_LIMITS.step_timeout_seconds
    )
    parser.add_argument(
        "--task-timeout-seconds", type=float, default=_LIMITS.task_timeout_seconds
    )
    args = parser.parse_args(argv)
    try:
        case_files = tuple(args.case_file) if args.case_file else _CASE_FILES
        expected_paths = {path.resolve() for path in _CASE_FILES}
        if (
            len(case_files) != len(expected_paths)
            or {path.resolve() for path in case_files} != expected_paths
        ):
            raise ValueError("select both reviewed case files in data/selected")
        limits = Limits(
            max_steps=args.max_steps,
            max_depth=args.max_depth,
            max_nodes=args.max_nodes,
            max_candidates=args.max_candidates,
            step_timeout_seconds=args.step_timeout_seconds,
            task_timeout_seconds=args.task_timeout_seconds,
        )
        run_selected(
            Path.cwd(),
            args.output,
            args.records,
            case_files,
            limits,
            task=args.task,
            run_id=args.run_id,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
