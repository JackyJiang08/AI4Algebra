"""Command-line entry points for solving, auditing and training on curated proofs."""

import argparse
import os
import sqlite3
import sys
from pathlib import Path
from typing import Literal, TextIO

from ai4algebra.candidates import BudgetError
from ai4algebra.config import RunConfig, load_config
from ai4algebra.contracts import Certificate, Identifier, Record, Verdict
from ai4algebra.corpus import Corpus
from ai4algebra.evaluation import EvaluationPlan, HeldOutSplit, evaluate, load_training
from ai4algebra.lean_bridge import BridgeError
from ai4algebra.search import SearchOptions, SearchStatus
from ai4algebra.training import TrainingOptions, TrainingPlan, train
from ai4algebra.training._artifacts import (
    ArtifactRef,
    CatalogIdentity,
    RunDirectory,
    RunIdentity,
    SearchFiles,
)
from ai4algebra.training._runtime import ApiAccounting, LeanCalls, ProofRuntime

_DEFAULT_MANIFEST = Path("data/manifests/elementary.json")


class _SolvePlan(Record):
    kind: Literal["solve"] = "solve"
    identity: RunIdentity
    task_id: Identifier
    mode: Literal["best_first", "deterministic"]
    search: SearchOptions


class _SolveResult(Record):
    run_id: Identifier
    plan: ArtifactRef
    status: SearchStatus
    reason: str
    files: SearchFiles | None = None
    lean_calls: LeanCalls = LeanCalls()
    api: ApiAccounting = ApiAccounting()
    replay_command: tuple[str, ...] = ()


class _VerifyPlan(Record):
    kind: Literal["verify"] = "verify"
    identity: RunIdentity
    task_id: Identifier
    certificate: Certificate


class _VerifyResult(Record):
    run_id: Identifier
    plan: ArtifactRef
    verdict: Verdict
    verdict_file: ArtifactRef
    lean_calls: LeanCalls


def _console_print(message: str, *, file: TextIO | None = None) -> None:
    stream = sys.stdout if file is None else file
    try:
        print(message, file=stream)
    except UnicodeEncodeError:
        encoding = stream.encoding or "ascii"
        print(
            message.encode(encoding, "backslashreplace").decode(encoding), file=stream
        )


def _task_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--manifest",
        type=Path,
        default=_DEFAULT_MANIFEST,
        help="public curated corpus manifest, default is elementary",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        help="pinned Lake project, inferred from the manifest by default",
    )
    parser.add_argument("--config", type=Path, help="JSON run settings")
    parser.add_argument(
        "--dotenv", type=Path, help="run environment file, default .env"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="use deterministic proposals even if the environment enables OpenAI",
    )


def _output_args(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument(
        "--output",
        type=Path,
        required=required,
        help="directory for versioned results and proof artifacts",
    )
    parser.add_argument(
        "--run-id",
        help="explicit run identifier, otherwise derived from the output directory",
    )


def _search_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--probes-per-node", type=int, default=4)
    parser.add_argument(
        "--stop-on-closure", action=argparse.BooleanOptionalAction, default=False
    )
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--max-depth", type=int)
    parser.add_argument("--max-nodes", type=int)
    parser.add_argument("--max-candidates", type=int)
    parser.add_argument("--step-timeout-seconds", type=float)
    parser.add_argument("--task-timeout-seconds", type=float)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai4algebra",
        description="Search for proofs and independently check them with pinned Lean.",
    )
    group = parser.add_subparsers(dest="command", required=True)
    check = group.add_parser(
        "corpus-check",
        help="validate public task statements, splits and premise policy",
    )
    _task_args(check)
    _output_args(check, required=False)
    solve = group.add_parser(
        "solve", help="search for a verified proof of one corpus task"
    )
    _task_args(solve)
    _output_args(solve)
    _search_args(solve)
    solve.add_argument("--task", required=True)
    solve.add_argument(
        "--mode", choices=("best_first", "deterministic"), default="best_first"
    )
    verify = group.add_parser(
        "verify", help="independently replay and audit an exported certificate"
    )
    _task_args(verify)
    _output_args(verify)
    verify.add_argument("--task", required=True)
    verify.add_argument("--certificate", type=Path, required=True)
    training = group.add_parser(
        "train", help="collect verified warmup rollouts and train DDQN"
    )
    _task_args(training)
    _output_args(training)
    _search_args(training)
    training.add_argument(
        "--task",
        action="append",
        default=[],
        help="validated train task, repeat to select several",
    )
    training.add_argument("--seed", type=int, default=7)
    training.add_argument("--warmup-episodes", type=int, default=1)
    training.add_argument(
        "--episodes",
        type=int,
        default=1,
        help="DDQN rollout episodes after verified warmup",
    )
    training.add_argument("--updates-per-episode", type=int, default=2)
    training.add_argument("--batch-size", type=int, default=2)
    evaluation = group.add_parser(
        "evaluate", help="compare frozen policies on a held-out split"
    )
    _task_args(evaluation)
    _output_args(evaluation)
    _search_args(evaluation)
    evaluation.add_argument(
        "--training-run",
        type=Path,
        action="append",
        required=True,
        help="completed training directory, repeat for independently trained seeds",
    )
    evaluation.add_argument("--split", choices=("validation", "test"), default="test")
    evaluation.add_argument("--retrieval-weight", type=float, default=0.5)
    return parser


def _config(args: argparse.Namespace) -> RunConfig:
    env = dict(os.environ)
    if args.offline or args.command in ("verify", "corpus-check"):
        env["AI4ALGEBRA_LLM_PROVIDER"] = "deterministic"
        env["AI4ALGEBRA_ALLOW_PAID_API"] = "false"
    for name in (
        "max_steps",
        "max_depth",
        "max_nodes",
        "max_candidates",
        "step_timeout_seconds",
        "task_timeout_seconds",
    ):
        value = getattr(args, name, None)
        if value is not None:
            env[f"AI4ALGEBRA_{name.upper()}"] = str(value)
    return load_config(args.config, environ=env, dotenv_path=args.dotenv)


def _paths(args: argparse.Namespace) -> tuple[Path, Path]:
    manifest: Path = args.manifest
    if args.project_root is not None:
        root = Path(args.project_root).resolve()
        return (root / manifest).resolve(), root
    manifest = manifest.resolve()
    for parent in manifest.parents:
        if (parent / "lean-toolchain").is_file() and (
            parent / "lake-manifest.json"
        ).is_file():
            return manifest, parent
    raise ValueError(
        "manifest is outside a pinned Lean project; specify --project-root"
    )


def _run(args: argparse.Namespace) -> int:
    config = _config(args)
    manifest, project = _paths(args)
    corpus = Corpus.open(manifest, source_root=project)
    catalog = CatalogIdentity.capture(corpus, project)
    if args.command == "corpus-check":
        if args.output is not None:
            destination = RunDirectory(args.output)
            with destination.writer():
                destination.put("corpus.json", catalog)
        _console_print(
            f"{catalog.corpus_id} has {len(catalog.tasks)} assigned tasks and {len(corpus.problems())} validated statements."
        )
        subclaims = sum(task.source_scope == "subclaim" for task in catalog.tasks)
        if subclaims:
            _console_print(
                f"{subclaims} mapped task(s) cover a stated subclaim of their source tag."
            )
        for excluded_task, reason in corpus.exclusions():
            _console_print(f"{excluded_task} is excluded. {reason}")
        return 0

    directory = RunDirectory(args.output)
    identity = RunIdentity.capture(
        args.run_id or directory.default_run_id, catalog, config, project
    )
    if args.command in ("solve", "verify"):
        with directory.writer():
            return _run_output(
                args, manifest, project, corpus, identity, config, directory
            )
    return _run_output(args, manifest, project, corpus, identity, config, directory)


def _run_output(
    args: argparse.Namespace,
    manifest: Path,
    project: Path,
    corpus: Corpus,
    identity: RunIdentity,
    config: RunConfig,
    directory: RunDirectory,
) -> int:
    catalog = identity.catalog
    if args.command == "verify":
        if directory.path("verification.json").exists():
            raise ValueError("output already holds a completed verification")
        problem = next(
            problem for problem in corpus.problems() if problem.task_id == args.task
        )
        certificate = Certificate.from_json(args.certificate.read_bytes())
        verification = _VerifyPlan(
            identity=identity, task_id=problem.task_id, certificate=certificate
        )
        plan_file = directory._plan(verification)
        runtime = ProofRuntime(corpus, project, config, directory, identity.run_id)
        verdict, calls = runtime.verify(problem, certificate)
        file = directory.put("verdict.json", verdict)
        directory.put(
            "verification.json",
            _VerifyResult(
                run_id=identity.run_id,
                plan=plan_file,
                verdict=verdict,
                verdict_file=file,
                lean_calls=calls,
            ),
        )
        _console_print(
            f"Lean audit {verdict.status}. Verdict at {directory.path(file.path)}"
        )
        return {"accepted": 0, "rejected": 1, "indeterminate": 3}[verdict.status]

    options = SearchOptions(
        probes_per_node=args.probes_per_node, stop_on_closure=args.stop_on_closure
    )
    if args.command == "solve":
        task = next(task for task in catalog.tasks if task.task_id == args.task)
        if directory.path("solve.json").exists():
            raise ValueError("output already holds a completed solve")
        plan_file = directory._plan(
            _SolvePlan(
                identity=identity, task_id=task.task_id, mode=args.mode, search=options
            )
        )
        if task.exclusion_reason is not None:
            directory.put(
                "solve.json",
                _SolveResult(
                    run_id=identity.run_id,
                    plan=plan_file,
                    status="unsupported",
                    reason=task.exclusion_reason,
                ),
            )
            _console_print(
                f"No validated Lean statement is available for {task.task_id}. {task.exclusion_reason}"
            )
            return 1
        problem = next(
            problem for problem in corpus.problems() if problem.task_id == task.task_id
        )
        runtime = ProofRuntime(corpus, project, config, directory, identity.run_id)
        execution = runtime.search(
            problem, mode=args.mode, options=options, episode_id=identity.run_id
        )
        report = execution.report
        files = directory.archive_search("result", report)
        replay: tuple[str, ...] = ()
        if files.proof is not None:
            replay = (
                "python",
                "-m",
                "ai4algebra",
                "verify",
                "--offline",
                "--manifest",
                str(manifest),
                "--project-root",
                str(project),
                "--task",
                task.task_id,
                "--certificate",
                str(directory.path(files.proof.certificate.path)),
                "--output",
                str(directory.path("recheck")),
            )
        directory.put(
            "solve.json",
            _SolveResult(
                run_id=identity.run_id,
                plan=plan_file,
                status=report.status,
                reason=report.reason,
                files=files,
                lean_calls=execution.lean_calls,
                api=runtime.api_accounting(),
                replay_command=replay,
            ),
        )
        _console_print(f"Goal  {problem.lean_statement}")
        if problem.binders:
            _console_print(f"Assumptions  {' '.join(problem.binders)}")
        if files.proof is not None:
            _console_print(
                f"Verified proof at {directory.path(files.proof.proof.path)}"
            )
            _console_print(
                f"Replayable certificate at {directory.path(files.proof.certificate.path)}"
            )
        else:
            _console_print(f"Search ended with {report.status} ({report.reason}).")
        return (
            0
            if report.status == "verified"
            else 3
            if report.status == "infrastructure_error"
            else 1
        )

    if args.command == "train":
        settings = TrainingOptions(
            seed=args.seed,
            warmup_episodes=args.warmup_episodes,
            episodes=args.episodes,
            updates_per_episode=args.updates_per_episode,
            batch_size=args.batch_size,
        )
        training_plan = TrainingPlan.make(
            identity, corpus, settings, options, tuple(args.task)
        )
        if (
            directory.path("training.json").exists()
            or directory.path("episodes").exists()
        ):
            raise ValueError(
                "training output already contains a run; use a fresh output directory"
            )
        runtime = ProofRuntime(corpus, project, config, directory, identity.run_id)
        trained = train(corpus, training_plan, directory, runtime)
        _console_print(
            f"Collected {trained.collected_transitions} transitions and ran {len(trained.updates)} optimizer updates."
        )
        if trained.evaluation_inputs is None:
            _console_print(
                f"Warmup produced no verified training trajectory. Report at {directory.path('training.json')}"
            )
            return 1
        _console_print(
            f"Frozen evaluation checkpoint at {directory.path(trained.evaluation_inputs.checkpoint.path)}"
        )
        return 0

    frozen = tuple(
        sorted(
            (
                load_training(
                    path, corpus, catalog, expected_code_digest=identity.code_digest
                )
                for path in args.training_run
            ),
            key=lambda item: item.identity.seed,
        )
    )
    if any(
        directory.root.is_relative_to(item.directory.root)
        or item.directory.root.is_relative_to(directory.root)
        for item in frozen
    ):
        raise ValueError("evaluation output must be separate from frozen training runs")
    split: HeldOutSplit = args.split
    evaluation_plan = EvaluationPlan(
        identity=identity,
        search=options,
        split=split,
        retrieval_weight=args.retrieval_weight,
        runs=tuple(item.identity for item in frozen),
        provider_condition="live" if config.paid_enabled else "deterministic",
    )
    runtime = ProofRuntime(corpus, project, config, directory, identity.run_id)
    result = evaluate(corpus, evaluation_plan, frozen, directory, runtime)
    for count in result.per_seed:
        _console_print(
            f"Seed {count.seed} {count.mode} verified {count.verified}/{count.assigned} assigned and {count.verified}/{count.validated} validated tasks."
        )
    _console_print(f"Evaluation report at {directory.path('evaluation.json')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except StopIteration:
        _console_print(
            "The requested task is absent or lacks a validated statement.",
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError, KeyError, BudgetError, sqlite3.Error) as exc:
        _console_print(str(exc), file=sys.stderr)
        return 2
    except BridgeError as exc:
        _console_print(str(exc), file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        return 130
