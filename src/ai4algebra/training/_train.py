"""Collect verified warmup rollouts and train on the exact saved decisions."""

from collections import Counter, deque
from collections.abc import Mapping
from dataclasses import asdict
from typing import Annotated, Literal

from numpy.random import Generator, SeedSequence, default_rng
from pydantic import Field

from ai4algebra.contracts import Digest, Identifier, Problem, Record, digest_json
from ai4algebra.corpus import Corpus
from ai4algebra.learning import (
    CandidateDDQN,
    CheckpointMetadata,
    CollectedSample,
    DDQNConfig,
)
from ai4algebra.memory import ReturnMemory
from ai4algebra.representation import EncoderConfig, FeatureEncoder
from ai4algebra.search import (
    ActionPolicy,
    DDQNPolicy,
    DeterministicPolicy,
    SearchOptions,
    SearchReport,
    SearchStatus,
    Work,
)

from ._artifacts import ArtifactRef, RunDirectory, RunIdentity, SearchFiles
from ._runtime import ApiAccounting, LeanCalls, SearchRuntime


class TrainingOptions(Record):
    seed: Annotated[int, Field(ge=0, le=2**63 - 1)] = 7
    warmup_episodes: Annotated[int, Field(gt=0)] = 1
    episodes: Annotated[int, Field(ge=0)] = 1
    updates_per_episode: Annotated[int, Field(gt=0)] = 2
    batch_size: Annotated[int, Field(gt=0)] = 2
    replay_capacity: Annotated[int, Field(gt=0)] = 128
    return_capacity: Annotated[int, Field(gt=0)] = 128
    epsilon: Annotated[float, Field(ge=0, le=1)] = 0.1
    retrieval_weight: Annotated[float, Field(ge=0, le=1)] = 0.5


class TrainingPlan(Record):
    kind: Literal["train"] = "train"
    identity: RunIdentity
    settings: TrainingOptions
    search: SearchOptions
    encoder: EncoderConfig
    encoder_digest: Digest
    ddqn: DDQNConfig
    action_seed: int
    replay_seed: int
    task_ids: tuple[Identifier, ...]

    @classmethod
    def make(
        cls,
        identity: RunIdentity,
        corpus: Corpus,
        settings: TrainingOptions,
        search: SearchOptions,
        task_ids: tuple[str, ...] = (),
    ) -> "TrainingPlan":
        allowed = {problem.task_id for problem in corpus.problems("train")}
        if not task_ids:
            task_ids = tuple(sorted(allowed))
        if (
            not task_ids
            or len(set(task_ids)) != len(task_ids)
            or not set(task_ids) <= allowed
        ):
            raise ValueError("training requires distinct validated train-split tasks")
        initial, action, replay = (
            int(stream.generate_state(1)[0])
            for stream in SeedSequence(settings.seed).spawn(3)
        )
        encoder = FeatureEncoder()
        return cls(
            identity=identity,
            settings=settings,
            search=search,
            encoder=encoder.config,
            encoder_digest=encoder.encoder_digest,
            ddqn=DDQNConfig(seed=initial, target_update_interval=2),
            action_seed=action,
            replay_seed=replay,
            task_ids=task_ids,
        )


class FilterCount(Record):
    reason: Identifier
    count: int


class TrainingEpisode(Record):
    episode_id: Identifier
    task_id: Identifier
    phase: Literal["warmup", "ddqn"]
    status: SearchStatus
    work: Work
    lean_calls: LeanCalls
    files: SearchFiles
    samples: tuple[ArtifactRef, ...]
    filtered: tuple[FilterCount, ...]
    publication_step: int | None
    published_returns: int
    truncated_samples: int


class OptimizerUpdate(Record):
    phase: Literal["warmup", "ddqn"]
    sample_digests: tuple[Digest, ...]
    loss: float | None
    target_mean: float | None
    used_samples: int
    missing_next_observations: int
    no_eligible_next_actions: int
    bootstrapped_truncations: int
    update_steps: int
    target_synced: bool


class FrozenTrainingFiles(Record):
    checkpoint: ArtifactRef
    checkpoint_digest: Digest
    metadata: CheckpointMetadata
    return_memory: ArtifactRef


class TrainingReport(Record):
    run_id: Identifier
    plan: ArtifactRef
    status: Literal["trained", "warmup_unverified"]
    episodes: tuple[TrainingEpisode, ...]
    updates: tuple[OptimizerUpdate, ...]
    collected_transitions: int
    retained_replay: int
    verified_episodes: int
    published_returns: int
    retained_returns: int
    cutoff: int
    api: ApiAccounting
    evaluation_inputs: FrozenTrainingFiles | None


def _collect(
    report: SearchReport,
    catalog: Mapping[str, Problem],
    directory: RunDirectory,
    prefix: str,
    episode_start: int,
) -> tuple[
    tuple[CollectedSample, ...], tuple[ArtifactRef, ...], tuple[FilterCount, ...]
]:
    if report.mode != "rollout" or report.problem.split != "train":
        raise ValueError("training requires a single train-split rollout")
    if any(
        attempt.collection_step != episode_start + index
        for index, attempt in enumerate(report.attempts)
    ):
        raise ValueError("search did not preserve the collection clock")
    by_step = {attempt.collection_step: attempt for attempt in report.attempts}
    accepted: list[CollectedSample] = []
    references = []
    seen: set[int] = set()
    previous_step = episode_start - 1
    for sample in report.samples:
        captured = CollectedSample.restore(
            sample.to_json(),
            task_sources=catalog,
            expected_artifact_digest=sample.artifact_digest,
        )
        transition = captured.trace.transition
        attempt = by_step.get(transition.collection_step)
        if (
            transition.episode_id != report.episode_id
            or transition.task_id != report.problem.task_id
            or transition.branch_id != "rollout"
            or transition.collection_step <= previous_step
            or attempt is None
            or attempt.candidate.candidate_id != transition.chosen_candidate_id
            or attempt.encoded != captured.sample.decision
            or attempt.candidate_set != transition.candidate_set
            or attempt.result.observation != transition.next_observation
            or attempt.outcome != transition.outcome
            or (transition.terminated and report.status != "verified")
            or transition.reward
            != (
                report.options.verified_reward
                if transition.terminated
                else -report.options.action_cost
            )
        ):
            raise ValueError(
                "collected sample does not match the recorded training action"
            )
        if transition.truncated:
            if (
                transition.next_observation != report.last_observation
                or transition.next_candidate_set != report.final_candidate_set
                or transition.collection_step
                != episode_start + len(report.attempts) - 1
            ):
                raise ValueError(
                    "truncated sample must use the final observed decision"
                )
        elif not transition.terminated:
            following = by_step.get(transition.collection_step + 1)
            if following is None or following.encoded != captured.sample.next_decision:
                raise ValueError(
                    "sample successor encoding differs from the following recorded decision"
                )
        reference = directory.put(
            f"{prefix}/samples/{len(accepted):03d}.json", captured
        )
        previous_step = transition.collection_step
        seen.add(transition.collection_step)
        accepted.append(captured)
        references.append(reference)
    filtered = Counter(
        "missing_continuation"
        if attempt.outcome in ("advanced", "rejected")
        else attempt.outcome
        for attempt in report.attempts
        if attempt.collection_step not in seen
    )
    return (
        tuple(accepted),
        tuple(references),
        tuple(
            FilterCount(reason=key, count=number)
            for key, number in sorted(filtered.items())
        ),
    )


def _optimize(
    learner: CandidateDDQN,
    replay: deque[CollectedSample],
    rng: Generator,
    settings: TrainingOptions,
    phase: Literal["warmup", "ddqn"],
) -> tuple[OptimizerUpdate, ...]:
    population = tuple(replay)
    batch_size = min(settings.batch_size, len(population))
    results = []
    for _ in range(settings.updates_per_episode):
        selected = tuple(
            population[int(index)]
            for index in rng.choice(len(population), size=batch_size, replace=False)
        )
        metrics = learner.update(tuple(item.sample for item in selected))
        results.append(
            OptimizerUpdate.model_validate(
                {
                    "phase": phase,
                    "sample_digests": tuple(item.artifact_digest for item in selected),
                    **asdict(metrics),
                }
            )
        )
    return tuple(results)


def train(
    corpus: Corpus,
    plan: TrainingPlan,
    directory: RunDirectory,
    runtime: SearchRuntime,
) -> TrainingReport:
    """Run fresh training; evaluation checkpoints contain the resulting frozen policies."""
    with directory.writer():
        return _train(corpus, plan, directory, runtime)


def _train(
    corpus: Corpus,
    plan: TrainingPlan,
    directory: RunDirectory,
    runtime: SearchRuntime,
) -> TrainingReport:
    plan = TrainingPlan.from_json(plan.to_json())
    if directory.path("training.json").exists() or directory.path("episodes").exists():
        raise ValueError(
            "training output already contains a run; use a fresh output directory"
        )
    catalog = {problem.task_id: problem for problem in corpus.problems("train")}
    if not plan.task_ids or not set(plan.task_ids) <= catalog.keys():
        raise ValueError("training plan contains an unvalidated or held-out task")
    encoder = FeatureEncoder(plan.encoder)
    identity = plan.identity
    if (
        encoder.encoder_digest != plan.encoder_digest
        or identity.catalog.policy_digest != corpus.policy_digest
        or identity.catalog.corpus_digest
        != digest_json(corpus.manifest.model_dump(mode="json"))
        or identity.catalog.partition_digest != corpus.manifest.partition_digest
    ):
        raise ValueError("training plan encoder or policy does not match")
    plan_file = directory._plan(plan)
    settings = plan.settings
    learner = CandidateDDQN(encoder, corpus.policy_digest, plan.ddqn)
    memory = ReturnMemory(
        settings.return_capacity,
        gamma=plan.ddqn.gamma,
        feature_version=plan.encoder_digest,
        state_size=encoder.state_size,
        policy_digest=corpus.policy_digest,
        task_sources=catalog,
        run_id=identity.run_id,
    )
    policy = DDQNPolicy(
        learner,
        epsilon=settings.epsilon,
        rng=default_rng(plan.action_seed),
        memory=memory,
        retrieval_weight=settings.retrieval_weight,
    )
    rng = default_rng(plan.replay_seed)
    replay: deque[CollectedSample] = deque(maxlen=settings.replay_capacity)
    history = []
    updates: list[OptimizerUpdate] = []
    clock = verified = collected = published = 0
    for index in range(settings.warmup_episodes + settings.episodes):
        warmup = index < settings.warmup_episodes
        if not warmup and not verified:
            break
        phase: Literal["warmup", "ddqn"] = "warmup" if warmup else "ddqn"
        task = catalog[plan.task_ids[index % len(plan.task_ids)]]
        episode_id = f"{identity.run_id}-episode-{index:04d}"
        phase_policy: ActionPolicy = DeterministicPolicy() if warmup else policy
        result = runtime.search(
            task,
            mode="rollout",
            options=plan.search,
            episode_id=episode_id,
            policy=phase_policy,
            encoder=encoder,
            collection_step=clock,
        )
        report = SearchReport.from_json(result.report.to_json())
        if (
            report.problem != task
            or report.episode_id != episode_id
            or report.limits != identity.config.limits
            or report.options != plan.search
            or report.policy_name != phase_policy.name
            or report.policy_digest != corpus.policy_digest
        ):
            raise ValueError("search rollout differs from the frozen training plan")
        prefix = f"episodes/{index:04d}"
        files = directory.archive_search(prefix, report)
        samples, references, filtered = _collect(
            report, catalog, directory, prefix, clock
        )
        clock += len(report.attempts)
        publication = None
        this_published = 0
        if (
            report.status == "verified"
            and len(samples) == len(report.attempts)
            and samples
        ):
            assert report.certificate is not None and report.verdict is not None
            this_published = memory.publish(
                tuple(sample.trace.transition for sample in samples),
                report.verdict,
                clock,
                state_features=tuple(
                    sample.sample.decision.state for sample in samples
                ),
                certificate=report.certificate,
            )
            if this_published:
                publication = clock
                clock += 1
                verified += 1
        replay.extend(samples)
        collected += len(samples)
        published += this_published
        history.append(
            TrainingEpisode(
                episode_id=episode_id,
                task_id=task.task_id,
                phase=phase,
                status=report.status,
                work=report.work,
                lean_calls=result.lean_calls,
                files=files,
                samples=references,
                filtered=filtered,
                publication_step=publication,
                published_returns=this_published,
                truncated_samples=sum(sample.sample.truncated for sample in samples),
            )
        )
        if verified and (not warmup or index + 1 == settings.warmup_episodes):
            updates.extend(_optimize(learner, replay, rng, settings, phase))

    frozen_files = None
    retained_returns = 0
    if updates:
        frozen = memory.freeze(clock)
        retained_returns = len(frozen)
        memory_file = directory.put("return-memory.json", frozen.to_json())
        metadata = CheckpointMetadata(
            run_id=identity.run_id,
            policy_digest=corpus.policy_digest,
            corpus_digest=identity.catalog.corpus_digest,
            source_digest=identity.catalog.source_digest,
            run_manifest_digest=digest_json(plan.model_dump(mode="json")),
            memory_digest=frozen.artifact_digest,
            memory_cutoff=clock,
        )
        digest = learner.save(directory.path("checkpoint.json"), metadata)
        frozen_files = FrozenTrainingFiles(
            checkpoint=directory.ref("checkpoint.json"),
            checkpoint_digest=digest,
            metadata=metadata,
            return_memory=memory_file,
        )
    result_report = TrainingReport(
        run_id=identity.run_id,
        plan=plan_file,
        status="trained" if frozen_files is not None else "warmup_unverified",
        episodes=tuple(history),
        updates=tuple(updates),
        collected_transitions=collected,
        retained_replay=len(replay),
        verified_episodes=verified,
        published_returns=published,
        retained_returns=retained_returns,
        cutoff=clock,
        api=runtime.api_accounting(),
        evaluation_inputs=frozen_files,
    )
    directory.put("training.json", result_report)
    return result_report
