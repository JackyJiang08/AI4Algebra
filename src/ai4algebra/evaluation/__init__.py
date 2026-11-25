"""Frozen corpus evaluation with paired deterministic and learned policies."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from statistics import mean, stdev
from typing import Annotated, Literal, TypedDict

from pydantic import Field

from ai4algebra.contracts import Digest, Identifier, Record, digest_json
from ai4algebra.corpus import Corpus
from ai4algebra.learning import CandidateDDQN, CheckpointMetadata
from ai4algebra.memory import FrozenReturnMemory
from ai4algebra.representation import FeatureEncoder
from ai4algebra.search import (
    Choice,
    DDQNPolicy,
    Decision,
    DeterministicPolicy,
    SearchOptions,
    SearchReport,
    SearchStatus,
    Work,
)
from ai4algebra.training import TrainingPlan, TrainingReport
from ai4algebra.training._artifacts import (
    ArtifactRef,
    CatalogIdentity,
    RunDirectory,
    RunIdentity,
    SearchFiles,
)
from ai4algebra.training._runtime import ApiAccounting, LeanCalls, SearchRuntime

BenchmarkMode = Literal["deterministic", "ddqn", "ddqn_retrieval"]
HeldOutSplit = Literal["validation", "test"]
MODES: tuple[BenchmarkMode, ...] = ("deterministic", "ddqn", "ddqn_retrieval")


class FrozenInput(Record):
    training_run: Identifier
    training_report: ArtifactRef
    seed: int
    update_steps: int
    encoder_digest: Digest
    checkpoint_digest: Digest
    memory_digest: Digest
    memory_cutoff: int


@dataclass(frozen=True)
class FrozenTraining:
    directory: RunDirectory
    learner: CandidateDDQN
    encoder: FeatureEncoder
    memory: FrozenReturnMemory
    identity: FrozenInput
    catalog: CatalogIdentity
    code_digest: str


def load_training(
    directory: Path,
    corpus: Corpus,
    expected: CatalogIdentity,
    *,
    expected_code_digest: str,
) -> FrozenTraining:
    artifact = RunDirectory(directory)
    report_ref = artifact.ref("training.json")
    report = TrainingReport.from_json(artifact.read(report_ref))
    files = report.evaluation_inputs
    if (
        report.status != "trained"
        or files is None
        or not report.updates
        or not report.verified_episodes
    ):
        raise ValueError("training run has no verified frozen evaluation inputs")
    plan = TrainingPlan.from_json(artifact.read(report.plan))
    if plan.identity.catalog != expected:
        raise ValueError(
            "training corpus, split, source, Lean environment or candidate generator differs"
        )
    if plan.identity.code_digest != expected_code_digest:
        raise ValueError(
            "training runtime source digest differs from the current implementation"
        )
    encoder = FeatureEncoder(plan.encoder)
    if (
        encoder.encoder_digest != plan.encoder_digest
        or report.run_id != plan.identity.run_id
    ):
        raise ValueError("training run or encoder identity differs")
    task_sources = {problem.task_id: problem for problem in corpus.problems("train")}
    if not plan.task_ids or not set(plan.task_ids) <= task_sources.keys():
        raise ValueError("training input contains held-out or unvalidated tasks")
    memory_digest = files.metadata.memory_digest
    if memory_digest is None or files.metadata.memory_cutoff != report.cutoff:
        raise ValueError("training memory cutoff differs from saved training report")
    metadata = CheckpointMetadata(
        run_id=report.run_id,
        policy_digest=expected.policy_digest,
        corpus_digest=expected.corpus_digest,
        source_digest=expected.source_digest,
        run_manifest_digest=digest_json(plan.model_dump(mode="json")),
        memory_digest=memory_digest,
        memory_cutoff=report.cutoff,
    )
    if metadata != files.metadata:
        raise ValueError("checkpoint metadata differs from the recorded training plan")
    memory = FrozenReturnMemory.from_json(
        artifact.read(files.return_memory),
        run_id=report.run_id,
        task_sources=task_sources,
        feature_version=encoder.encoder_digest,
        state_size=encoder.state_size,
        policy_digest=expected.policy_digest,
        cutoff=report.cutoff,
        expected_artifact_digest=memory_digest,
    )
    artifact.read(files.checkpoint)
    learner = CandidateDDQN.load(
        artifact.path(files.checkpoint.path),
        encoder=encoder,
        expected_metadata=metadata,
        expected_artifact_digest=files.checkpoint_digest,
    )
    if (
        learner.config != plan.ddqn
        or learner.update_steps != report.updates[-1].update_steps
        or len(memory) != report.retained_returns
    ):
        raise ValueError(
            "checkpoint parameters or frozen memory counts differ from the training report"
        )
    return FrozenTraining(
        artifact,
        learner,
        encoder,
        memory,
        FrozenInput(
            training_run=report.run_id,
            training_report=report_ref,
            seed=plan.settings.seed,
            update_steps=learner.update_steps,
            encoder_digest=encoder.encoder_digest,
            checkpoint_digest=files.checkpoint_digest,
            memory_digest=memory_digest,
            memory_cutoff=report.cutoff,
        ),
        expected,
        expected_code_digest,
    )


class EvaluationPlan(Record):
    kind: Literal["evaluate"] = "evaluate"
    identity: RunIdentity
    search: SearchOptions
    split: HeldOutSplit
    retrieval_weight: Annotated[float, Field(gt=0, le=1)] = 0.5
    runs: tuple[FrozenInput, ...]
    modes: tuple[BenchmarkMode, ...] = MODES
    provider_condition: Literal["deterministic", "live"]


class EvaluationTrial(Record):
    seed: int
    mode: BenchmarkMode
    task_id: Identifier
    family_id: Identifier
    source_scope: Literal["full", "subclaim"]
    validated: bool
    status: SearchStatus
    reason: str
    depth: int = 0
    work: Work = Work()
    lean_calls: LeanCalls = LeanCalls()
    invalid_tactics: int = 0
    step_timeouts: int = 0
    provider_timeouts: int = 0
    provider_budget_fallbacks: int = 0
    audit_rejections: int = 0
    audit_indeterminate: int = 0
    replay_failures: int = 0
    retrieval_decisions: int = 0
    retrieval_hit_decisions: int = 0
    retrieval_matches: int = 0
    settled_usd: str = "0"
    added_outstanding_usd: str = "0"
    settled_input_tokens: int = 0
    settled_output_tokens: int = 0
    settled_cached_tokens: int = 0
    added_unresolved_requests: int = 0
    files: SearchFiles | None = None


class SeedCounts(Record):
    seed: int
    mode: BenchmarkMode
    assigned: int
    validated: int
    verified: int
    candidate_exhausted: int
    budget_exhausted: int
    verification_rejected: int
    infrastructure_error: int
    unsupported: int
    full_source_assigned: int
    full_source_validated: int
    full_source_verified: int
    subclaim_assigned: int
    subclaim_verified: int


class SeedVariation(Record):
    n_seeds: int
    mean: float | None
    sample_std: float | None
    minimum: float | None
    maximum: float | None

    @classmethod
    def summarize(cls, values: Sequence[float]) -> "SeedVariation":
        return cls(
            n_seeds=len(values),
            mean=mean(values) if values else None,
            sample_std=stdev(values) if len(values) > 1 else None,
            minimum=min(values) if values else None,
            maximum=max(values) if values else None,
        )


class ModeRates(Record):
    mode: BenchmarkMode
    verified_per_assigned: SeedVariation
    verified_per_validated: SeedVariation


class PairedDifference(Record):
    reference: BenchmarkMode
    comparison: BenchmarkMode
    verified_per_assigned_delta: SeedVariation
    verified_per_validated_delta: SeedVariation


class EvaluationReport(Record):
    run_id: Identifier
    plan: ArtifactRef
    split: HeldOutSplit
    provider_condition: Literal["deterministic", "live"]
    trials: tuple[EvaluationTrial, ...]
    per_seed: tuple[SeedCounts, ...]
    across_seeds: tuple[ModeRates, ...]
    paired_differences: tuple[PairedDifference, ...]
    api: ApiAccounting


class _CountedRetrieval(DDQNPolicy):
    def __init__(self, trained: FrozenTraining, weight: float) -> None:
        super().__init__(
            trained.learner,
            memory=trained.memory,
            retrieval_weight=weight,
            before_step=trained.memory.cutoff,
        )
        self.memory = trained.memory
        self.decisions = 0
        self.hits = 0
        self.matches = 0

    def choose(self, decision: Decision) -> Choice:
        selected = super().choose(decision)
        assert decision.encoded is not None
        matches = self.memory.query(
            decision.encoded.state,
            decision.candidate_set,
            exclude_episode=decision.episode_id,
        )
        self.decisions += 1
        self.hits += int(bool(matches))
        self.matches += len(matches)
        return selected


class _TrialWork(TypedDict):
    invalid_tactics: int
    step_timeouts: int
    provider_timeouts: int
    provider_budget_fallbacks: int
    audit_rejections: int
    audit_indeterminate: int
    replay_failures: int


def _trial_work(report: SearchReport) -> _TrialWork:
    probes = [
        probe
        for generation in report.generations
        for probe in generation.probes
        if not probe.reused
    ]
    actions = [attempt for attempt in report.attempts if not attempt.reused_probe]
    verdicts = [
        attempt.verdict for attempt in report.attempts if attempt.verdict is not None
    ]
    return {
        "invalid_tactics": sum(probe.status == "rejected" for probe in probes)
        + sum(attempt.result.status == "rejected" for attempt in actions),
        "step_timeouts": max(
            int("step_timeout" in report.budget_reasons),
            sum(probe.status == "timeout" for probe in probes)
            + sum(attempt.result.status == "timeout" for attempt in actions),
        ),
        "provider_timeouts": sum(
            generation.provider_status == "timeout" for generation in report.generations
        ),
        "provider_budget_fallbacks": sum(
            generation.provider_status == "budget_exhausted"
            for generation in report.generations
        ),
        "audit_rejections": sum(verdict.status == "rejected" for verdict in verdicts),
        "audit_indeterminate": sum(
            verdict.status == "indeterminate" for verdict in verdicts
        ),
        "replay_failures": sum(verdict.replay_passed is False for verdict in verdicts),
    }


def _counts(
    seed: int, mode: BenchmarkMode, trials: Sequence[EvaluationTrial]
) -> SeedCounts:
    rows = [trial for trial in trials if trial.seed == seed and trial.mode == mode]
    full_source = [trial for trial in rows if trial.source_scope == "full"]
    subclaims = [trial for trial in rows if trial.source_scope == "subclaim"]
    return SeedCounts(
        seed=seed,
        mode=mode,
        assigned=len(rows),
        validated=sum(trial.validated for trial in rows),
        verified=sum(trial.status == "verified" for trial in rows),
        candidate_exhausted=sum(
            trial.status == "candidate_exhausted" for trial in rows
        ),
        budget_exhausted=sum(trial.status == "budget_exhausted" for trial in rows),
        verification_rejected=sum(
            trial.status == "verification_rejected" for trial in rows
        ),
        infrastructure_error=sum(
            trial.status == "infrastructure_error" for trial in rows
        ),
        unsupported=sum(trial.status == "unsupported" for trial in rows),
        full_source_assigned=len(full_source),
        full_source_validated=sum(trial.validated for trial in full_source),
        full_source_verified=sum(trial.status == "verified" for trial in full_source),
        subclaim_assigned=len(subclaims),
        subclaim_verified=sum(trial.status == "verified" for trial in subclaims),
    )


def _seed_statistics(
    rows: tuple[SeedCounts, ...],
) -> tuple[tuple[ModeRates, ...], tuple[PairedDifference, ...]]:
    grouped = {
        mode: {row.seed: row for row in rows if row.mode == mode} for mode in MODES
    }
    rates = tuple(
        ModeRates(
            mode=mode,
            verified_per_assigned=SeedVariation.summarize(
                [
                    row.verified / row.assigned
                    for row in matches.values()
                    if row.assigned
                ]
            ),
            verified_per_validated=SeedVariation.summarize(
                [
                    row.verified / row.validated
                    for row in matches.values()
                    if row.validated
                ]
            ),
        )
        for mode, matches in grouped.items()
    )
    pairs: tuple[tuple[BenchmarkMode, BenchmarkMode], ...] = (
        ("deterministic", "ddqn"),
        ("deterministic", "ddqn_retrieval"),
        ("ddqn", "ddqn_retrieval"),
    )
    differences = []
    for reference, comparison in pairs:
        aligned = tuple(
            (left, grouped[comparison][seed])
            for seed, left in grouped[reference].items()
        )
        differences.append(
            PairedDifference(
                reference=reference,
                comparison=comparison,
                verified_per_assigned_delta=SeedVariation.summarize(
                    [
                        right.verified / right.assigned - left.verified / left.assigned
                        for left, right in aligned
                        if left.assigned and right.assigned
                    ]
                ),
                verified_per_validated_delta=SeedVariation.summarize(
                    [
                        right.verified / right.validated
                        - left.verified / left.validated
                        for left, right in aligned
                        if left.validated and right.validated
                    ]
                ),
            )
        )
    return rates, tuple(differences)


def evaluate(
    corpus: Corpus,
    plan: EvaluationPlan,
    trained: Sequence[FrozenTraining],
    directory: RunDirectory,
    runtime: SearchRuntime,
) -> EvaluationReport:
    """Run paired policies under identical per-task limits, using read-only learner inputs."""
    if any(
        directory.root.is_relative_to(item.directory.root)
        or item.directory.root.is_relative_to(directory.root)
        for item in trained
    ):
        raise ValueError("evaluation output must be separate from frozen training runs")
    with directory.writer():
        return _evaluate(corpus, plan, trained, directory, runtime)


def _evaluate(
    corpus: Corpus,
    plan: EvaluationPlan,
    trained: Sequence[FrozenTraining],
    directory: RunDirectory,
    runtime: SearchRuntime,
) -> EvaluationReport:
    plan = EvaluationPlan.from_json(plan.to_json())
    if not trained or tuple(item.identity for item in trained) != plan.runs:
        raise ValueError("frozen training inputs differ from the evaluation plan")
    if len({item.identity.seed for item in trained}) != len(trained):
        raise ValueError("evaluation requires one independently trained run per seed")
    if any(
        not item.learner.frozen
        or item.catalog != plan.identity.catalog
        or item.code_digest != plan.identity.code_digest
        for item in trained
    ):
        raise ValueError(
            "evaluation requires frozen inputs compatible with the declared catalog"
        )
    if plan.identity.catalog.corpus_digest != digest_json(
        corpus.manifest.model_dump(mode="json")
    ):
        raise ValueError("evaluation corpus differs from the frozen plan")
    if plan.modes != MODES:
        raise ValueError("evaluation requires all three paired policy conditions")
    if directory.path("evaluation.json").exists():
        raise ValueError("evaluation output already holds a completed report")
    tasks = tuple(
        task for task in plan.identity.catalog.tasks if task.split == plan.split
    )
    if not tasks:
        raise ValueError("evaluation split has no assigned tasks")
    eligible = {problem.task_id: problem for problem in corpus.problems(plan.split)}
    plan_file = directory._plan(plan)
    trials: list[EvaluationTrial] = []
    for item in trained:
        seed = item.identity.seed
        for mode in plan.modes:
            for index, task in enumerate(tasks):
                problem = eligible.get(task.task_id)
                if problem is None:
                    trials.append(
                        EvaluationTrial(
                            seed=seed,
                            mode=mode,
                            task_id=task.task_id,
                            family_id=task.family_id,
                            source_scope=task.source_scope,
                            validated=False,
                            status="unsupported",
                            reason=task.exclusion_reason or "missing validated task",
                        )
                    )
                    continue
                retrieval = (
                    _CountedRetrieval(item, plan.retrieval_weight)
                    if mode == "ddqn_retrieval"
                    else None
                )
                policy = retrieval or (
                    DeterministicPolicy()
                    if mode == "deterministic"
                    else DDQNPolicy(item.learner)
                )
                episode_id = f"{plan.identity.run_id}-seed-{seed}-{mode}-{index:03d}"
                before = runtime.api_accounting()
                execution = runtime.search(
                    problem,
                    mode="best_first",
                    options=plan.search,
                    policy=policy,
                    episode_id=episode_id,
                    encoder=item.encoder,
                )
                before = (
                    execution.api_before if execution.api_before is not None else before
                )
                after = runtime.api_accounting()
                report = SearchReport.from_json(execution.report.to_json())
                if (
                    report.problem != problem
                    or report.mode != "best_first"
                    or report.samples
                    or report.transitions
                    or report.episode_id != episode_id
                    or report.options != plan.search
                    or report.policy_name != policy.name
                    or report.limits != plan.identity.config.limits
                    or report.policy_digest != plan.identity.catalog.policy_digest
                    or report.eligibility_digest != task.eligibility_digest
                ):
                    raise ValueError("a trial differs from frozen evaluation inputs")
                files = directory.archive_search(
                    f"trials/{seed}/{mode}/{index:03d}", report
                )
                trials.append(
                    EvaluationTrial(
                        seed=seed,
                        mode=mode,
                        task_id=task.task_id,
                        family_id=task.family_id,
                        source_scope=task.source_scope,
                        validated=True,
                        status=report.status,
                        reason=report.reason,
                        depth=len(report.certificate.steps)
                        if report.certificate is not None
                        else max((node.depth for node in report.nodes), default=0),
                        work=report.work,
                        lean_calls=execution.lean_calls,
                        files=files,
                        retrieval_decisions=0
                        if retrieval is None
                        else retrieval.decisions,
                        retrieval_hit_decisions=0
                        if retrieval is None
                        else retrieval.hits,
                        retrieval_matches=0 if retrieval is None else retrieval.matches,
                        settled_usd=str(
                            Decimal(after.settled_usd) - Decimal(before.settled_usd)
                        ),
                        added_outstanding_usd=str(
                            Decimal(after.outstanding_usd)
                            - Decimal(before.outstanding_usd)
                        ),
                        settled_input_tokens=after.settled_input_tokens
                        - before.settled_input_tokens,
                        settled_output_tokens=after.settled_output_tokens
                        - before.settled_output_tokens,
                        settled_cached_tokens=after.settled_cached_tokens
                        - before.settled_cached_tokens,
                        added_unresolved_requests=after.unresolved_requests
                        - before.unresolved_requests,
                        **_trial_work(report),
                    )
                )
    per_seed = tuple(
        _counts(item.identity.seed, mode, trials)
        for item in trained
        for mode in plan.modes
    )
    across_seeds, paired = _seed_statistics(per_seed)
    result = EvaluationReport(
        run_id=plan.identity.run_id,
        plan=plan_file,
        split=plan.split,
        provider_condition=plan.provider_condition,
        trials=tuple(trials),
        api=runtime.api_accounting(),
        per_seed=per_seed,
        across_seeds=across_seeds,
        paired_differences=paired,
    )
    directory.put("evaluation.json", result)
    return result


__all__ = [
    "EvaluationPlan",
    "EvaluationReport",
    "FrozenTraining",
    "HeldOutSplit",
    "evaluate",
    "load_training",
]
