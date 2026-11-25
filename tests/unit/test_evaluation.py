"""Fast training/evaluation contract tests using controlled search results."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

import pytest

from ai4algebra.candidates import GENERATOR_VERSION
from ai4algebra.config import Limits, RunConfig
from ai4algebra.contracts import (
    Candidate,
    CandidateSet,
    Goal,
    Observation,
    Problem,
    Snapshot,
    StepResult,
    Transition,
    Verdict,
    digest_json,
)
from ai4algebra.corpus import Corpus
from ai4algebra.evaluation import EvaluationPlan, evaluate, load_training
from ai4algebra.lean_bridge import environment_digest
from ai4algebra.learning import CollectedSample, encode_decision
from ai4algebra.representation import DecisionContext, FeatureEncoder
from ai4algebra.search import (
    ActionPolicy,
    Attempt,
    Decision,
    SearchMode,
    SearchOptions,
    SearchReport,
    Work,
)
from ai4algebra.training import TrainingOptions, TrainingPlan, train
from ai4algebra.training._artifacts import CatalogIdentity, RunDirectory, RunIdentity
from ai4algebra.training._runtime import ApiAccounting, LeanCalls, TaskExecution
from ai4algebra.training._train import _collect
from ai4algebra.verification import Verifier

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / "data/manifests/elementary.json"
_OPTIONS = SearchOptions(probes_per_node=2)
_CONFIG = RunConfig(limits=Limits(max_steps=8))


@dataclass
class ControlledRuntime:
    corpus: Corpus
    warmup_fails: bool = False
    mislabel_learned: bool = False
    pause: tuple[Event, Event] | None = None
    called: list[tuple[str, str, SearchOptions]] = field(default_factory=list)

    def api_accounting(self) -> ApiAccounting:
        return ApiAccounting()

    def search(
        self,
        problem: Problem,
        *,
        mode: SearchMode,
        options: SearchOptions,
        episode_id: str,
        policy: ActionPolicy | None = None,
        encoder: FeatureEncoder | None = None,
        collection_step: int = 0,
    ) -> TaskExecution:
        assert policy is not None and encoder is not None
        if self.pause is not None:
            started, release = self.pause
            started.set()
            assert release.wait(timeout=5.0)
        eligibility = self.corpus.eligibility_policy(problem)
        self.called.append((problem.split, policy.name, options))
        environment = environment_digest(_ROOT, problem.imports)
        root = Snapshot(
            session_id=episode_id,
            snapshot_id="root",
            environment_digest=environment,
            prefix_digest=digest_json(()),
        )
        observation = Observation(
            snapshot=root,
            goals=(
                Goal(goal_id="g0", target="True", expression='["const","True",[]]'),
            ),
        )
        candidate = Candidate(
            operation="reflexivity", goal_id="g0", generator_version=GENERATOR_VERSION
        )
        candidates = CandidateSet(
            state_digest=observation.state_digest,
            policy_digest=eligibility.policy_digest,
            candidates=(candidate,),
            eligible=(True,),
        )
        encoded = encode_decision(
            encoder,
            observation,
            candidates,
            DecisionContext(remaining_depth=8, remaining_steps=7, eligible_count=1),
        )
        choice = policy.choose(
            Decision(observation, candidates, encoded, episode_id, collection_step)
        )
        assert choice.candidate_id == candidate.candidate_id
        arguments = dict(
            problem=problem,
            policy_digest=eligibility.policy_digest,
            eligibility_digest=eligibility.eligibility_digest,
            policy_name="deterministic"
            if self.mislabel_learned and mode == "best_first"
            else policy.name,
            mode=mode,
            episode_id=episode_id,
            limits=_CONFIG.limits,
            options=options,
            verification_reserve_seconds=30.0,
            continuation_reserve_seconds=10.0,
            nodes=(),
            generations=(),
        )
        if (mode == "rollout" and self.warmup_fails) or (
            mode == "best_first" and policy.name == "ddqn" and "-seed-7-" in episode_id
        ):
            report = SearchReport.model_validate(
                arguments
                | dict(
                    status="budget_exhausted",
                    reason="steps",
                    budget_reasons=("steps",),
                    work=Work(opens=1, probe_calls=1),
                    attempts=(),
                    last_observation=observation,
                    final_candidate_set=candidates,
                )
            )
            return TaskExecution(report, LeanCalls(observer_requests=2))
        child = Snapshot(
            session_id=episode_id,
            snapshot_id="child",
            environment_digest=environment,
            prefix_digest=digest_json((candidate.candidate_id,)),
        )
        final = Observation(snapshot=child, goals=())
        final_set = CandidateSet(
            state_digest=final.state_digest,
            policy_digest=eligibility.policy_digest,
            candidates=(),
            eligible=(),
        )
        certificate = Verifier(_ROOT).build_certificate(
            problem, (candidate,), eligibility
        )
        verdict = Verdict(
            status="accepted",
            replay_passed=True,
            type_passed=True,
            axioms_passed=True,
            dependencies_passed=True,
            lean_version="fixture",
            mathlib_revision="fixture",
            certificate_digest=digest_json(certificate.model_dump(mode="json")),
        )
        attempt = Attempt(
            node_id="root",
            collection_step=collection_step,
            candidate_set=candidates,
            candidate=candidate,
            encoded=encoded,
            reused_probe=True,
            result=StepResult(status="closed", snapshot=child, observation=final),
            outcome="verified",
            child_id="child",
            certificate=certificate,
            verdict=verdict,
        )
        samples: tuple[CollectedSample, ...] = ()
        transitions: tuple[Transition, ...] = ()
        if mode == "rollout":
            transition = Transition(
                episode_id=episode_id,
                branch_id="rollout",
                task_id=problem.task_id,
                split="train",
                collection_step=collection_step,
                observation=observation,
                candidate_set=candidates,
                chosen_candidate_id=candidate.candidate_id,
                reward=1.0,
                next_observation=final,
                next_candidate_set=final_set,
                terminated=True,
                truncated=False,
                outcome="verified",
                feature_version=encoder.encoder_digest,
            )
            transitions = (transition,)
            samples = (
                CollectedSample.capture(
                    transition,
                    encoded,
                    None,
                    encoder=encoder,
                    task_sources={problem.task_id: problem},
                ),
            )
        report = SearchReport.model_validate(
            arguments
            | dict(
                status="verified",
                reason="verified",
                budget_reasons=(),
                work=Work(
                    opens=1,
                    probe_calls=1,
                    selected_actions=1,
                    reused_probes=1,
                    verifier_calls=1,
                ),
                attempts=(attempt,),
                last_observation=final,
                final_candidate_set=final_set,
                samples=samples,
                transitions=transitions,
                certificate=certificate,
                verdict=verdict,
            )
        )
        return TaskExecution(
            report, LeanCalls(observer_requests=2, verifier_requests=1)
        )


def _fixture() -> tuple[Corpus, CatalogIdentity]:
    corpus = Corpus.open(_MANIFEST)
    return corpus, CatalogIdentity.capture(corpus, _ROOT)


def _snapshot(path: Path) -> dict[str, bytes]:
    return {
        str(file.relative_to(path)): file.read_bytes()
        for file in path.rglob("*")
        if file.is_file()
    }


def test_seeded_training_and_paired_evaluation_preserve_frozen_artifacts(
    tmp_path: Path,
) -> None:
    corpus, catalog = _fixture()
    runtime = ControlledRuntime(corpus)
    trained = []
    snapshots = []
    for seed in (7, 11):
        folder = RunDirectory(tmp_path / f"train-{seed}")
        plan = TrainingPlan.make(
            RunIdentity.capture(f"train-{seed}", catalog, _CONFIG, _ROOT),
            corpus,
            TrainingOptions(seed=seed),
            _OPTIONS,
            ("group-inverse-identity",),
        )
        report = train(corpus, plan, folder, runtime)
        assert (
            report.verified_episodes
            == report.published_returns
            == report.collected_transitions
            == 2
        )
        assert [episode.publication_step for episode in report.episodes] == [1, 3]
        assert report.cutoff == 4 and report.updates[-1].update_steps == 4
        assert len(report.updates[0].sample_digests) == 1
        assert report.episodes[0].files.proof is not None
        reference = report.episodes[0].samples[0]
        loaded = CollectedSample.from_json(folder.read(reference))
        assert loaded.artifact_digest == report.updates[0].sample_digests[0]
        item = load_training(
            folder.root, corpus, catalog, expected_code_digest=plan.identity.code_digest
        )
        assert item.learner.frozen and item.memory.cutoff == report.cutoff
        snapshots.append(_snapshot(folder.root))
        trained.append(item)

    assert [name for _, name, _ in runtime.called] == [
        "deterministic",
        "ddqn_retrieval",
    ] * 2
    assert all(split == "train" for split, _, _ in runtime.called)
    runtime.called.clear()
    eval_plan = EvaluationPlan(
        identity=RunIdentity.capture("held-out", catalog, _CONFIG, _ROOT),
        search=_OPTIONS,
        split="test",
        runs=tuple(item.identity for item in trained),
        provider_condition="deterministic",
    )
    output = RunDirectory(tmp_path / "eval")
    evaluation = evaluate(corpus, eval_plan, trained, output, runtime)
    assert [name for _, name, _ in runtime.called] == [
        "deterministic",
        "ddqn",
        "ddqn_retrieval",
    ] * 2
    assert all(
        split == "test" and options == _OPTIONS for split, _, options in runtime.called
    )
    assert [count.verified for count in evaluation.per_seed] == [1, 0, 1, 1, 1, 1]
    assert all(count.assigned == count.validated == 1 for count in evaluation.per_seed)
    assert len(evaluation.trials) == 6 and any(
        trial.lean_calls.total == 3 for trial in evaluation.trials
    )
    q_rates = evaluation.across_seeds[1].verified_per_assigned
    assert (q_rates.n_seeds, q_rates.mean, q_rates.minimum, q_rates.maximum) == (
        2,
        0.5,
        0.0,
        1.0,
    )
    assert q_rates.sample_std == pytest.approx(0.70710678)
    q_delta = evaluation.paired_differences[0].verified_per_validated_delta
    assert (q_delta.n_seeds, q_delta.mean, q_delta.minimum, q_delta.maximum) == (
        2,
        -0.5,
        -1.0,
        0.0,
    )
    assert all(
        _snapshot(item.directory.root) == snapshot
        for item, snapshot in zip(trained, snapshots, strict=True)
    )
    runtime.mislabel_learned = True
    with pytest.raises(ValueError, match="trial differs from frozen evaluation inputs"):
        evaluate(
            corpus, eval_plan, trained, RunDirectory(tmp_path / "mislabelled"), runtime
        )
    with pytest.raises(ValueError, match="validation.*test"):
        evaluate(
            corpus,
            eval_plan.model_copy(update={"split": "train"}),
            trained,
            RunDirectory(tmp_path / "invalid-split"),
            runtime,
        )
    with pytest.raises(ValueError, match="separate from frozen"):
        evaluate(
            corpus,
            eval_plan,
            trained,
            RunDirectory(trained[0].directory.root / "child"),
            runtime,
        )


def test_warmup_must_find_verified_trajectory_before_updating(tmp_path: Path) -> None:
    corpus, catalog = _fixture()
    runtime = ControlledRuntime(corpus, warmup_fails=True)
    folder = RunDirectory(tmp_path / "train")
    plan = TrainingPlan.make(
        RunIdentity.capture("warmup", catalog, _CONFIG, _ROOT),
        corpus,
        TrainingOptions(episodes=3),
        _OPTIONS,
    )
    report = train(corpus, plan, folder, runtime)
    assert report.status == "warmup_unverified" and not report.updates
    assert len(runtime.called) == 1 and report.evaluation_inputs is None
    assert not folder.path("checkpoint.json").exists()
    with pytest.raises(ValueError, match="no verified frozen"):
        load_training(
            folder.root, corpus, catalog, expected_code_digest=plan.identity.code_digest
        )

    with pytest.raises(ValueError, match="train-split"):
        TrainingPlan.make(
            plan.identity, corpus, plan.settings, plan.search, ("ring-add-cancel-pair",)
        )


def test_same_plan_cannot_train_into_an_active_output(tmp_path: Path) -> None:
    corpus, catalog = _fixture()
    folder = RunDirectory(tmp_path / "train")
    plan = TrainingPlan.make(
        RunIdentity.capture("train", catalog, _CONFIG, _ROOT),
        corpus,
        TrainingOptions(episodes=0),
        _OPTIONS,
    )
    started, release = Event(), Event()
    owner = ControlledRuntime(corpus, pause=(started, release))
    contender = ControlledRuntime(corpus, warmup_fails=True)
    with ThreadPoolExecutor(max_workers=1) as executor:
        initial = executor.submit(train, corpus, plan, folder, owner)
        try:
            assert started.wait(timeout=5.0)
            with pytest.raises(ValueError, match="another process is writing"):
                train(corpus, plan, folder, contender)
        finally:
            release.set()
        trained = initial.result(timeout=5.0)
    assert trained.status == "trained" and contender.called == []
    saved = trained.episodes[0].files.trace
    assert SearchReport.from_json(folder.read(saved)).status == "verified"


def test_frozen_training_rejects_changed_generator_and_artifacts(
    tmp_path: Path,
) -> None:
    corpus, catalog = _fixture()
    runtime = ControlledRuntime(corpus)
    folder = RunDirectory(tmp_path / "train")
    plan = TrainingPlan.make(
        RunIdentity.capture("train", catalog, _CONFIG, _ROOT),
        corpus,
        TrainingOptions(episodes=0),
        _OPTIONS,
    )
    report = train(corpus, plan, folder, runtime)
    with pytest.raises(ValueError, match="candidate generator differs"):
        load_training(
            folder.root,
            corpus,
            catalog.model_copy(update={"generator_digest": digest_json("changed")}),
            expected_code_digest=plan.identity.code_digest,
        )
    with pytest.raises(ValueError, match="runtime source digest differs"):
        load_training(
            folder.root,
            corpus,
            catalog,
            expected_code_digest=digest_json("another runtime"),
        )
    assert report.evaluation_inputs is not None
    folder.put("training.json", report.model_copy(update={"cutoff": report.cutoff + 1}))
    with pytest.raises(ValueError, match="training memory cutoff differs"):
        load_training(
            folder.root, corpus, catalog, expected_code_digest=plan.identity.code_digest
        )
    folder.put("training.json", report)
    with folder.path(report.evaluation_inputs.return_memory.path).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="artifact digest mismatch"):
        load_training(
            folder.root, corpus, catalog, expected_code_digest=plan.identity.code_digest
        )


def test_collector_rejects_reencoded_successor_at_the_same_observation(
    tmp_path: Path,
) -> None:
    corpus, _ = _fixture()
    problem = next(
        item
        for item in corpus.problems("train")
        if item.task_id == "group-inverse-identity"
    )
    encoder = FeatureEncoder()
    from ai4algebra.search import DeterministicPolicy

    report = (
        ControlledRuntime(corpus)
        .search(
            problem,
            mode="rollout",
            options=_OPTIONS,
            episode_id="fixture",
            policy=DeterministicPolicy(),
            encoder=encoder,
            collection_step=1,
        )
        .report
    )
    (last,) = report.samples
    (following,) = report.attempts
    actual = last.trace.transition.observation
    snapshot = Snapshot(
        session_id=actual.snapshot.session_id,
        snapshot_id="prior",
        environment_digest=actual.snapshot.environment_digest,
        prefix_digest=digest_json("prior"),
    )
    prior = Observation(snapshot=snapshot, goals=actual.goals)
    candidate = Candidate(
        operation="intro", goal_id="g0", generator_version=GENERATOR_VERSION
    )
    candidates = CandidateSet(
        state_digest=prior.state_digest,
        policy_digest=corpus.policy_digest,
        candidates=(candidate,),
        eligible=(True,),
    )
    initial = encode_decision(
        encoder, prior, candidates, DecisionContext(remaining_depth=8, eligible_count=1)
    )
    reencoded = encode_decision(
        encoder,
        actual,
        following.candidate_set,
        DecisionContext(remaining_depth=2, eligible_count=1),
    )
    transition = Transition(
        episode_id=report.episode_id,
        branch_id="rollout",
        task_id=problem.task_id,
        split="train",
        collection_step=0,
        observation=prior,
        candidate_set=candidates,
        chosen_candidate_id=candidate.candidate_id,
        reward=-_OPTIONS.action_cost,
        next_observation=actual,
        next_candidate_set=following.candidate_set,
        terminated=False,
        truncated=False,
        outcome="advanced",
        feature_version=encoder.encoder_digest,
    )
    catalog = {problem.task_id: problem}
    altered = CollectedSample.capture(
        transition, initial, reencoded, encoder=encoder, task_sources=catalog
    )
    first = Attempt(
        node_id="prior",
        collection_step=0,
        candidate_set=candidates,
        candidate=candidate,
        encoded=initial,
        reused_probe=True,
        result=StepResult(
            status="advanced", snapshot=actual.snapshot, observation=actual
        ),
        outcome="advanced",
        child_id="root",
    )
    modified = SearchReport.from_json(
        report.model_copy(
            update={
                "attempts": (first, following),
                "samples": (altered, last),
                "transitions": (transition, last.trace.transition),
            }
        ).to_json()
    )
    with pytest.raises(ValueError, match="successor encoding differs"):
        _collect(modified, catalog, RunDirectory(tmp_path), "rollout", 0)
