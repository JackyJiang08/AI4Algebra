"""Exercise 11 through premise retrieval, real DDQN training and frozen search.

The bootstrap problem is independently authored ZMod 3 arithmetic. No Gold source,
manual, archived solution or preselected target proof is loaded by this runner.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import deque
from pathlib import Path

from numpy.random import default_rng

from ai4algebra.candidates import (
    BudgetLedger,
    CandidateGenerator,
    LemmaRule,
    OpenAIProposer,
    PremiseIndex,
)
from ai4algebra.config import Limits, RunConfig, load_config
from ai4algebra.contracts import Problem, SourceRef, digest_json
from ai4algebra.lean_bridge import LeanBridge, environment_digest
from ai4algebra.lean_bridge.protocol import _worker_environment
from ai4algebra.learning import CandidateDDQN, CheckpointMetadata, DDQNConfig
from ai4algebra.memory import ReturnMemory
from ai4algebra.representation import FeatureEncoder
from ai4algebra.search import (
    DDQNPolicy,
    DeterministicPolicy,
    SearchOptions,
    SearchReport,
    solve,
)
from ai4algebra.search._policy import Choice, Decision
from ai4algebra.selected_benchmark import (
    CaseFile,
    _problem,
    _runtime_files,
    _sha256,
    _source_sections,
    _statement,
)
from ai4algebra.training._artifacts import RunDirectory
from ai4algebra.training._train import TrainingOptions, _collect, _optimize
from ai4algebra.verification import EligibilityPolicy, Verifier

PREMISES = ("addOrderOf_eq_iff", "Nat.zero_lt_succ")
LIMITS = Limits(
    max_depth=64,
    max_nodes=128,
    max_candidates=8,
    max_steps=256,
    step_timeout_seconds=120.0,
    task_timeout_seconds=2400.0,
    max_input_tokens=8192,
    max_output_tokens=1536,
)
OPTIONS = SearchOptions(stop_on_closure=False, continuation_probes=0)


def extract_index(
    root: Path, directory: RunDirectory, problem: Problem
) -> PremiseIndex:
    """Extract actual kernel types and complete dependency closures, not guessed signatures."""
    names = ", ".join(f"``{name}" for name in PREMISES)
    source = (
        "\n".join(f"import {name}" for name in problem.imports)
        + """
import AI4Algebra.Bridge.Main
open Lean Elab Meta
run_cmd Lean.Elab.Command.liftTermElabM do
  let env ← getEnv
  for name in (NAMES : List Name) do
    let info ← getConstInfo name
    let mut pending := info.getUsedConstantsAsSet.toList
    let mut seen : NameSet := {}
    while let current :: remaining := pending do
      pending := remaining
      if seen.contains current then continue
      if seen.size >= 8192 then throwError "signature dependency limit"
      seen := seen.insert current
      let some dependency := env.checked.get.find? current
        | throwError "missing dependency {current}"
      pending := dependency.getUsedConstantsAsSet.toList ++ pending
    let some moduleIndex := env.getModuleIdxFor? name
      | throwError "missing declaration module"
    let moduleName := env.allImportedModuleNames[moduleIndex.toNat]!
    let output := Json.mkObj [
      ("name", toJson name.toString),
      ("statement", toJson (← ppExpr info.type).pretty),
      ("expression", toJson (AI4Algebra.Bridge.encodeExpr {} info.type).compress),
      ("module", toJson moduleName.toString),
      ("dependencies", toJson (seen.toList.map Name.toString))]
    IO.println ("PREMISE:" ++ output.compress)
""".replace("NAMES", f"[{names}]")
    )
    path = directory.path("premise-extraction.lean")
    directory.put("premise-extraction.lean", source)
    result = subprocess.run(
        ["lake", "env", "lean", str(path)],
        cwd=root,
        env=_worker_environment(),
        capture_output=True,
        encoding="utf-8",
        timeout=300,
    )
    directory.put("premise-extraction.log", result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("premise extraction failed; see premise-extraction.log")
    rules_list = []
    for line in result.stdout.splitlines():
        if not line.startswith("PREMISE:"):
            continue
        decoded = json.loads(line.removeprefix("PREMISE:"))
        decoded["dependencies"] = tuple(decoded["dependencies"])
        decoded["required_imports"] = problem.imports
        rules_list.append(LemmaRule.model_validate(decoded))
    rules = tuple(rules_list)
    if tuple(rule.name for rule in rules) != PREMISES:
        raise ValueError("premise extraction did not cover the reviewed declarations")
    index = PremiseIndex(
        environment_digest=environment_digest(root, problem.imports),
        imports=problem.imports,
        rules=rules,
    )
    directory.put("premise-index.json", index)
    return index


def problems_and_policies(
    root: Path,
) -> tuple[tuple[Problem, Problem], tuple[EligibilityPolicy, ...]]:
    cases = CaseFile.from_json((root / "data/selected/group_cases.json").read_bytes())
    case = next(item for item in cases.cases if item.id == "exercise-11")
    source = (root / "data/training_questions.md").read_bytes()
    target = _problem(case, _sha256(source), _source_sections(source)[11])
    warmup_text = "Prove that the additive order of 1 in Z/3Z is 3."
    warmup = Problem(
        task_id="zmod3-order-warmup",
        source=SourceRef(
            kind="authored-fixture",
            source_id="zmod3-order-warmup",
            revision="1",
            location="data/selected/zmod3-warmup.md",
            content_digest=_sha256(
                (root / "data/selected/zmod3-warmup.md")
                .read_text(encoding="utf-8")
                .encode()
            ),
            attribution="AI4Algebra authored bootstrap exercise",
            license_ref="Repository license",
        ),
        informal_statement=warmup_text,
        family_id="selected-exercise-11",
        split="train",
        imports=target.imports,
        lean_name="AI4Algebra.Benchmarks.SelectedAttempt.zmod3_warmup",
        lean_statement="addOrderOf (1 : ZMod 3) = 3",
        mapping_evidence_id="zmod3-order-review",
    )
    policies = tuple(
        EligibilityPolicy(
            task_id=p.task_id,
            statement_digest=p.statement_digest,
            allowed_imports=p.imports,
            allowed_declarations=PREMISES,
            forbidden_declarations=(
                *case.forbidden_declarations,
                case.reference_declaration,
            ),
            forbidden_imports=("AI4Algebra.Benchmarks.Gold",),
        )
        for p in (warmup, target)
    )
    bundle = digest_json(tuple(p.eligibility_digest for p in policies))
    bundled = tuple(
        EligibilityPolicy.model_validate(
            p.model_dump(exclude={"policy_digest", "eligibility_digest"})
            | {"bundle_digest": bundle}
        )
        for p in policies
    )
    return (warmup, target), bundled


class TracedPolicy(DDQNPolicy):
    """Retain raw Q values and causal return matches alongside blended choices."""

    def __init__(
        self, learner: CandidateDDQN, memory: ReturnMemory, cutoff: int
    ) -> None:
        self.frozen_memory = memory.freeze(cutoff)
        self.learner = learner
        self.cutoff = cutoff
        self.events: list[dict[str, object]] = []
        super().__init__(
            learner, memory=self.frozen_memory, retrieval_weight=0.5, before_step=cutoff
        )

    def choose(self, decision: Decision) -> Choice:
        assert decision.encoded is not None
        returns = self.frozen_memory.query(
            decision.encoded.state,
            decision.candidate_set,
            before_step=self.cutoff,
            exclude_episode=decision.episode_id,
        )
        choice = super().choose(decision)
        self.events.append(
            {
                "episode_id": decision.episode_id,
                "cutoff": self.cutoff,
                "state_digest": decision.observation.state_digest,
                "eligible_count": sum(decision.candidate_set.eligible),
                "q_values": self.learner.scores(decision.encoded),
                "return_matches": returns,
                "blended_scores": {
                    item.candidate_id: item.score for item in choice.scores
                },
                "chosen_candidate_id": choice.candidate_id,
            }
        )
        return choice


def archive(
    root: Path,
    run_id: str,
    phase: str,
    problem: Problem,
    policy: EligibilityPolicy,
    report: SearchReport,
    *,
    offline: bool,
) -> None:
    branch = "succeeded" if report.status == "verified" else "failed"
    directory = RunDirectory(
        root / "records" / branch / run_id / problem.task_id / phase
    )
    if directory.root.exists():
        raise FileExistsError("attempt archive already exists")
    directory.put("problem.json", problem)
    directory.put("problem.md", problem.informal_statement + "\n")
    directory.put("statement.lean", _statement(problem))
    directory.put("eligibility.json", policy)
    directory.archive_search("evidence", report)
    directory.put(
        "outcome.md",
        f"# {phase}\n\n{report.status}: {report.reason}.\n\n"
        f"Policy: {report.policy_name}. Original artifacts: runs/{run_id}.\n"
        "Bootstrap is a separate authored training exercise; target search uses a frozen trained DDQN.\n"
        "No reference solution is read. Failed search does not imply a false theorem.\n"
        f"Reproduce: `python -m ai4algebra.selected_full --output runs/NEW-RUN{' --offline' if offline else ''}` with the recorded run settings.\n",
    )


def run(root: Path, output: Path, *, offline: bool = False) -> dict[str, object]:
    root, output = root.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(
            "use a new output directory; never overwrite prior evidence"
        )
    run_id = output.name
    if re.fullmatch(r"[a-zA-Z0-9]+(?:[._-][a-zA-Z0-9]+)*", run_id) is None:
        raise ValueError("run ID must be a portable name")
    if any(
        (root / "records" / branch / run_id).exists()
        for branch in ("succeeded", "failed")
    ):
        raise FileExistsError("run ID already archived")
    lock = root / "records/.locks" / run_id
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.mkdir()
    output.mkdir(parents=True)
    try:
        return _run_owned(root, output, offline=offline)
    except (Exception, KeyboardInterrupt) as error:
        directory = RunDirectory(output)
        summary_path = directory.path("summary.json")
        summary = json.loads(summary_path.read_bytes()) if summary_path.exists() else {}
        phase_path = directory.path("phase.json")
        phase = (
            json.loads(phase_path.read_bytes())
            if phase_path.exists()
            else {"phase": "configuration"}
        )
        summary.update(
            {"status": "pipeline_error", "error_type": type(error).__name__, **phase}
        )
        directory.put("summary.json", json.dumps(summary, indent=2))
        failure = RunDirectory(
            root / "records/failed" / run_id / "pipeline-infrastructure" / "attempt-001"
        )
        failure.put("outcome.json", json.dumps(summary, indent=2))
        failure.put(
            "outcome.md",
            f"Pipeline infrastructure failed ({type(error).__name__}); no additional proof result is claimed. Partial evidence: {output.as_posix()}.\n",
        )
        raise


def _run_owned(root: Path, output: Path, *, offline: bool) -> dict[str, object]:
    run_id = output.name
    directory = RunDirectory(output)
    config = RunConfig(limits=LIMITS) if offline else load_config()
    config = config.model_copy(update={"limits": LIMITS})
    tasks, policies = problems_and_policies(root)
    warmup, target = tasks
    directory.put(
        "run.json",
        json.dumps(
            {
                "run_id": run_id,
                "scope": "development train-family pipeline demonstration, not held-out evaluation",
                "config": config.model_dump(mode="json"),
                "limits": LIMITS.model_dump(mode="json"),
                "options": OPTIONS.model_dump(mode="json"),
                "runtime_files": _runtime_files(root),
                "problems": [p.model_dump(mode="json") for p in tasks],
                "policies": [p.model_dump(mode="json") for p in policies],
            },
            indent=2,
        ),
    )
    print("Extracting reviewed Mathlib premise signatures", flush=True)
    directory.put("phase.json", '{"phase":"premise-extraction"}')
    index = extract_index(root, directory, target)
    for rule in index.rules:
        if {rule.name, *rule.dependencies} & set(policies[0].forbidden_declarations):
            raise ValueError("retrieved premise depends on an excluded answer")
    encoder = FeatureEncoder()
    learner = CandidateDDQN(
        encoder, policies[0].policy_digest, DDQNConfig(seed=7, target_update_interval=2)
    )
    catalog = {p.task_id: p for p in tasks}
    memory = ReturnMemory(
        128,
        gamma=learner.config.gamma,
        feature_version=encoder.encoder_digest,
        state_size=encoder.state_size,
        policy_digest=learner.policy_digest,
        task_sources=catalog,
        run_id=run_id,
    )
    # One application ledger for this entire run, including both phases.
    ledger = (
        BudgetLedger(
            directory.path("provider-budget.sqlite"), run_id, config.api_budget_usd
        )
        if config.paid_enabled
        else None
    )
    proposer = OpenAIProposer(config, ledger) if ledger is not None else None

    def search(
        problem: Problem,
        eligibility: EligibilityPolicy,
        phase: str,
        policy: DeterministicPolicy | TracedPolicy,
        *,
        training: bool,
    ) -> SearchReport:
        print(f"Searching {problem.task_id}: {phase}, policy={policy.name}", flush=True)
        directory.put("phase.json", json.dumps({"phase": phase}))
        bridge = LeanBridge(root)
        report = solve(
            problem,
            eligibility,
            bridge,
            CandidateGenerator(
                problem,
                eligibility,
                bridge,
                premise_index=index,
                proposer=None if training else proposer,
                computational=True,
            ),
            Verifier(root, timeout_seconds=120.0),
            LIMITS,
            mode="rollout" if training else "best_first",
            options=OPTIONS,
            policy=policy,
            encoder=encoder,
            episode_id=f"{run_id}-{phase}",
        )
        directory.archive_search(phase, report)
        archive(root, run_id, phase, problem, eligibility, report, offline=offline)
        print(
            f"{phase}: {report.status}, {report.work.selected_actions} actions, {report.work.probe_calls} probes",
            flush=True,
        )
        return report

    summary: dict[str, object] = {"run_id": run_id, "status": "started"}
    try:
        boot = search(
            warmup, policies[0], "bootstrap", DeterministicPolicy(), training=True
        )
        summary["bootstrap_status"] = boot.status
        if boot.status != "verified":
            summary["status"] = "bootstrap_failed"
            return summary
        samples, _, filtered = _collect(boot, catalog, directory, "bootstrap", 0)
        if not samples or len(samples) != len(boot.attempts) or filtered:
            raise ValueError("bootstrap did not produce complete validated transitions")
        assert boot.verdict is not None and boot.certificate is not None
        clock = len(boot.attempts)
        published = memory.publish(
            tuple(s.trace.transition for s in samples),
            boot.verdict,
            clock,
            state_features=tuple(s.sample.decision.state for s in samples),
            certificate=boot.certificate,
        )
        clock += 1
        directory.put("phase.json", '{"phase":"optimizer"}')
        updates = _optimize(
            learner,
            deque(samples),
            default_rng(7),
            TrainingOptions(updates_per_episode=32, batch_size=len(samples)),
            "warmup",
        )
        directory.put(
            "updates.json",
            json.dumps([u.model_dump(mode="json") for u in updates], indent=2),
        )
        frozen = memory.freeze(clock)
        directory.put("return-memory.json", frozen.to_json())
        metadata = CheckpointMetadata(
            run_id=run_id,
            policy_digest=learner.policy_digest,
            corpus_digest=digest_json([p.model_dump(mode="json") for p in tasks]),
            source_digest=digest_json([p.source.content_digest for p in tasks]),
            memory_digest=frozen.artifact_digest,
            memory_cutoff=clock,
        )
        checkpoint = learner.save(directory.path("checkpoint.json"), metadata)
        loaded = CandidateDDQN.load(
            directory.path("checkpoint.json"),
            encoder=encoder,
            expected_metadata=metadata,
            expected_artifact_digest=checkpoint,
        )
        policy = TracedPolicy(loaded, memory, clock)
        summary.update(
            {
                "optimizer_updates": loaded.update_steps,
                "collected_transitions": len(samples),
                "published_returns": published,
                "checkpoint_digest": checkpoint,
                "memory_digest": frozen.artifact_digest,
                "memory_cutoff": clock,
            }
        )
        try:
            final = search(
                target, policies[1], "ddqn-retrieval", policy, training=False
            )
        finally:
            directory.put("decisions.json", json.dumps(policy.events, indent=2))
        summary.update(
            {
                "status": final.status,
                "reason": final.reason,
                "policy": final.policy_name,
                "q_decisions": len(policy.events),
                "return_hit_decisions": sum(
                    bool(event["return_matches"]) for event in policy.events
                ),
                "work": final.work.model_dump(mode="json"),
            }
        )
        return summary
    except (Exception, KeyboardInterrupt) as error:
        summary.update({"status": "pipeline_error", "error_type": type(error).__name__})
        raise
    finally:
        api = ledger.summary() if ledger is not None else None
        summary["api"] = {
            "settled_usd": str(api.spent_usd) if api else "0",
            "outstanding_usd": str(api.outstanding_usd) if api else "0",
            "reserved_requests": api.requests if api else 0,
        }
        directory.put("summary.json", json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        result = run(Path.cwd(), args.output, offline=args.offline)
    except (Exception, KeyboardInterrupt) as error:
        raise SystemExit(
            f"Pipeline failed ({type(error).__name__}); inspect the preserved run artifacts."
        ) from None
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
