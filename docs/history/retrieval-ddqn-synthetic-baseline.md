# Retrieval-guided Double DQN — Structure A

## Discovery and scope
No AGENTS.md exists in this repository or its ancestor directories. Existing code is a Lean skeleton (AI4Algebra/Basic.lean, AI4Algebra/Test.lean, lakefile.toml), with a README charter, and no training, replay, evaluation, Python configuration, or retrieval implementation. Existing validation: `lake build`, also used by .github/workflows/lean_action_ci.yml. Pre-existing untracked Papers/ is untouched.

Add an explicitly experimental Python/NumPy baseline on a synthetic chain environment, not Lean proof search. This does not complete the charter's prerequisite milestones. Retrieval guides actions and never certifies mathematics. No application runtime subagents exist; Structure A is development coordination only.

## Entry points
- Setup: `python -m venv .venv`, `.venv/Scripts/python.exe -m pip install -e ".[test]"`.
- Train: `python -m retrieval_ddqn.train --config configs/smoke.json --output runs/retrieval`; baseline adds `--disable-retrieval` and uses runs/baseline.
- Evaluate: `python -m retrieval_ddqn.evaluate --checkpoint runs/retrieval/checkpoint.json --episodes 10 --seed 101`.
- Test: `python -m pytest -q`. Existing Lean: `lake build`.

## Shared contracts (settled before delegation)
Python >=3.10, NumPy, pytest. Package retrieval_ddqn.
- Lead contracts.py: frozen `Transition(state: tuple[float,...], action: int, reward: float, next_state: tuple[float,...], terminated: bool, truncated: bool, step: int, episode_id: str, split: str = "train")`.
- Retrieval-owned retrieval.py: frozen `RetrievalRecord(state, action, discounted_return, transition_step, available_at, episode_id, split="train")`, tuple states. `RetrievalIndex(capacity, state_dim, action_count)` exposes `add(record)`, `query(state, *, before_step, exclude_episode_id=None, k=3, max_distance=0.01) -> dict[int,float]`, `to_records() -> list[dict]`, classmethod `from_records(records, *, capacity, state_dim, action_count) -> RetrievalIndex`, `__len__`.
- Learner-owned learner.py: `MLP(state_dim, action_count, hidden_dim, seed)`, `predict(states)` -> NumPy [batch,action]; `train(states, actions, targets, learning_rate)` -> scalar MSE; `copy_from(other)`, `state_dict()` JSON-compatible, `load_state_dict(data)`.
- `double_dqn_targets(rewards, terminated, next_online_q, next_target_q, gamma)` -> 1-D array. `DoubleDQNLearner(state_dim, action_count, hidden_dim, seed, gamma, learning_rate, target_update_interval)` owns online, target, update_steps; `update(transitions: Sequence[Transition]) -> dict` numeric loss/target_mean/update_steps; `state_dict()` / `load_state_dict(data)` round-trip networks and counter.
- Lead policy: matched action score = `(1-weight)*Q[a]+weight*retrieved[a]`; unmatched actions retain Q. Epsilon exploration follows blending. Bellman targets use raw network Q.

## Retrieval design
Index state/action/discounted reward-to-terminal returns from completed, terminated training episodes only, after completion. Do not index truncated episodes: their observed return is censored. Query includes current state, global transition cutoff and current episode ID. Euclidean nearest k records per action within max_distance; insertion-order tie breaking; mean returns per action.
Eligibility: split=train, transition_step < before_step, available_at < before_step, different episode ID if supplied. available_at is source episode's last transition step and must be >= transition_step. Reject non-training insertion and malformed/nonfinite records. Filter before ranking. FIFO capacity. Empty/no eligible matches falls back to network Q.
Train queries before stepping at global_step; increment global_step after transition. Completed memory has available_at=global_step-1. Eval restores a frozen training index and queries at checkpoint global_step. Eval never inserts experiences or trains, and uses eval- episode IDs. Checkpoints retain original availability metadata. Future records are excluded even if present in the index.

## Double DQN update
Online chooses a*=argmax Q_online(next_state,a). Target evaluates Q_target(next_state,a*). Target = reward + gamma*(1-terminated)*Q_target(next_state,a*). Termination suppresses bootstrap; time-limit truncation bootstraps from actual final observation (no auto-reset). Replay stores both flags. Two-layer ReLU MLP, manual NumPy gradients, MSE on selected actions. Target starts as exact online copy, then hard copies every target_update_interval optimizer updates. Targets do not backpropagate. Uniform bounded FIFO replay samples without replacement and rejects non-training records.

## Handoffs and ownership
### Lead: architecture and integration
- Objective/model: coordinator/current parent model; shared architecture, config, integration, final validation.
- Exact edit ownership: RETRIEVAL_DDQN_PLAN.md, README.md, .gitignore, pyproject.toml, configs/smoke.json, retrieval_ddqn/{__init__,contracts,config,environment,replay,policy,train,evaluate}.py, tests/test_integration.py.
- Dependencies: contracts before dispatch; integration waits for workers. Worker files reserved until return.
- Completion: retrieval effect/fallback/leakage checks, enabled/disabled seeded train/eval, independent review and final evidence.
- Validation: reproduce focused worker tests, full pytest, normal CLI smoke for both modes, attempt lake build.
- Return: integrated code, reproducible commands, observations and limitations.

### Implementer A: retrieval
- Objective/model: implement causal retrieval index; GPT-6.2 Astra Medium (gpt-6.2-astra, medium).
- Scope/ownership: ONLY retrieval_ddqn/retrieval.py and tests/test_retrieval.py. Implements settled API above. All other files reserved for lead/other owner.
- Dependencies: this settled retrieval contract; no learner dependency.
- Completion: known match, empty index, future transition/availability exclusion, same-episode exclusion, reject eval insertion, bounded capacity, deterministic ranking, validated serialization.
- Validation: `.venv/Scripts/python.exe -m pytest -q tests/test_retrieval.py`, all pass.
- Return: changed files, summary, check results, unresolved issues. No commits/shared edits.

### Implementer B: learner
- Objective/model: implement settled NumPy DDQN learner; GPT-6.2 Astra Medium (gpt-6.2-astra, medium).
- Scope/ownership: ONLY retrieval_ddqn/learner.py and tests/test_learner.py. Implements settled learner API; consumes lead contracts.py. Other files reserved.
- Dependencies: shared Transition contract and settled API. Independent of retrieval.
- Completion: exact numerical target where online/target argmax differ, terminal reward-only, truncation bootstrap, meaningful MLP gradient check, target initialization/sync, JSON round trip.
- Validation: `.venv/Scripts/python.exe -m pytest -q tests/test_learner.py`, all pass.
- Return: changed files, summary, check results, unresolved issues. No commits/shared edits.

### Independent reviewer: integrated review
- Objective/model: algorithm, leakage and regression review; GPT-6.2 Sol High (gpt-6.2-sol, high).
- Scope/ownership: read-only all combined changes; no edits.
- Dependencies: workers returned; lead inspected source and reproduced focused checks; integration and CLI smokes complete.
- Completion: prioritized findings with file/line references, repros, checks run, or explicit no findings. Cover targets/sync, truncation, train/eval isolation, cutoffs/checkpoint behavior.
- Validation: full pytest plus focused numerical/leakage checks; report exact commands.
- Return: findings, evidence, checks and residual risks. Lead resolves confirmed findings and reruns validation.

## Execution record
Design established before dispatch. All implementation assignments have returned, integration is complete, and final validation is recorded below.

### Integrated implementation and accepted ownership
- Implementer A delivered only retrieval_ddqn/retrieval.py and tests/test_retrieval.py: 19 tests passing.
- Implementer B delivered only retrieval_ddqn/learner.py and tests/test_learner.py: 6 tests passing (including parametrized cases).
- Lead inspected both source implementations and test diffs, reproduced their combined 25 tests, integrated both without interface changes, and added 11 integration cases in tests/test_integration.py. Shared files remained lead-owned throughout.
- Both workers used exactly GPT-6.2 Astra Medium. Independent reviewer uses GPT-6.2 Sol High and is read-only. No investigator or reusable agent role files were needed because discovery found no unresolved architecture question.
- Sandbox dependency setup stalled; approved installation outside the sandbox succeeded. Actual environment: Python 3.13.5, NumPy 2.5.5, pytest 9.2.0.

### Numerical and leakage evidence
- With online next Q = [-1, 4], target next Q = [10, -2], reward=2, gamma=0.25, online chooses action 1 and exact target is 1.5, not 4.5. A second nonterminal example yields -2; terminal example yields exactly reward=3.
- Through the real learner update with next-state online Q=[0,1], target Q=[9,2], reward=3, gamma=0.5: truncation yields 4; termination yields 3; both flags true also yields 3. Environment success at the horizon is terminal, while time limit alone truncates and exposes final observation.
- Central finite differences check every MLP parameter gradient; target stays unchanged after first update and copies online exactly after second update at interval=2. JSON restoration between syncs preserves the subsequent update exactly.
- Controlled retrieval: network Q=[0.4,0.2], retrieved action-1 return=1, weight=0.5 gives exact scores [0.4,0.6], flipping greedy action 0 to 1. Empty, unavailable, same-episode and disabled cases return action 0. A future reward of 100 cannot affect the decision.
- Training memory return is -0.01 + 0.9*1 = 0.89 in a known two-transition episode; unavailable until the final transition has completed. Incomplete/truncated episodes are not published; eval records are rejected by index, replay, and memory publishing. Eval tests forbid learner updates and index/replay insertion and assert byte-identical checkpoints and unchanged in-memory networks/index. Train/eval determinism is checked on repeated seeded runs in both modes.

### Workflow observations
All commands below executed from repository root. Config: configs/smoke.json, training seed 7, 40 episodes, 7 states, 12-step limit, hidden width 32, gamma 0.95, learning rate 0.01, batch 16, target sync every 20 updates, epsilon 0.8 to 0.1. Retrieval: capacity 2000, k=3 per action, radius 0.01, weight=0.5. Baseline changes only retrieval_enabled=false and output path. Eval: 10 greedy episodes, seed 101.

| Mode | Training steps / updates | Training mean return / success | Records / train retrieval hits | Eval steps / hits | Eval mean return / success |
|---|---:|---:|---:|---:|---:|
| Retrieval enabled | 223 / 208 | 0.828 / 0.875 | 163 / 172 | 35 / 35 | 0.975 / 1.0 |
| Retrieval disabled | 257 / 242 | 0.7185 / 0.775 | 0 / 0 | 35 / 0 | 0.975 / 1.0 |

Training mean losses: enabled 0.08315421541178815; disabled 0.06167054520050057. Different behavior produces different step/update counts despite identical episode budgets. These are workflow checks, not evidence of better sample efficiency or performance. A multi-seed, held-out benchmark with a fixed comparison budget would be needed for such claims.

### Reproduction commands (PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[test]'
.\.venv\Scripts\python.exe -m pytest -q tests/test_retrieval.py tests/test_learner.py
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp runs/final-pytest
.\.venv\Scripts\python.exe -m retrieval_ddqn.train --config configs/smoke.json --output runs/retrieval
.\.venv\Scripts\python.exe -m retrieval_ddqn.evaluate --checkpoint runs/retrieval/checkpoint.json --episodes 10 --seed 101
.\.venv\Scripts\python.exe -m retrieval_ddqn.train --config configs/smoke.json --output runs/baseline --disable-retrieval
.\.venv\Scripts\python.exe -m retrieval_ddqn.evaluate --checkpoint runs/baseline/checkpoint.json --episodes 10 --seed 101
lake build
```

Initial integrated validation: 25 focused tests passed, 35 total tests passed. Pytest emitted a nonfatal cache-write permission warning; `-p no:cacheprovider` can suppress cache creation in this environment. Existing `lake build` initially failed in sandbox with a TLS credential error; the approved outside-sandbox retry succeeded (4 jobs). No Lean files or workflows changed.

### Remaining limitations
- Synthetic finite-state environment only; no Lean interaction, theorem corpus, typed precondition matcher, or proof benchmark. One-hot Euclidean retrieval is a baseline, not semantic proof retrieval.
- Return memory averages behavior-policy returns from completed episodes and excludes censored episodes, which can introduce selection bias. No benefit claim is made. Queries scan bounded memory linearly; this is not a large-scale vector database.
- Checkpoints are versioned JSON evaluation artifacts; no training resume support (replay/RNG/partial episodes are not persisted). Imported records rely on honest training provenance labels, validated on insertion; the application itself never routes held-out data into memory.
- No runtime delegation or consequential external execution path was introduced.

### Independent review and final validation
Reviewer independently reproduced 25 focused and 35 pre-hardening integrated tests. Its default temporary directory was inaccessible, so it used a workspace `--basetemp`; no test logic failed. Independent scalar DDQN parity checks passed. A checkpoint fixture confirmed that high-value memory with available_at equal to cutoff cannot affect evaluation, and advancing the cutoff admits it.

No DDQN, runtime retrieval leakage, evaluation-freezing, or normal-checkpoint correctness findings. One low-priority failure-path concern: malformed source trajectories could partly update FIFO memory before raising validation errors. Lead removed an inaccurate atomicity docstring, then additionally staged validation of every record before real insertion and added a regression test proving a malformed terminal record cannot evict existing memory. README now explicitly says the entire truncated episode is excluded from retrieval memory. Reviewer follow-up on the fix is recorded below.

Lead final validation: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp runs/final-pytest` passed **36 tests**, without warnings. Both normal train/evaluation CLI pairs were rerun after the fix and exactly reproduced the table above. Existing Lean build passed (4 jobs). The cache-disabled, workspace-temp variant is recommended on this machine; the standard pytest command remains supported. Remaining limitations are listed above; no performance gain is claimed.

Reviewer follow-up confirmed the staging fix and independently passed the new regression and the full 36-test suite using `--basetemp runs/reviewer-final-pytest`. Additional capacity-1/2/3 checks preserved FIFO order and availability metadata for valid episodes. No remaining review findings. Final tracked whitespace check (`git diff --check`, with the per-command safe.directory setting required by this checkout) passed. All planned assignments and validation are complete; existing user files remain untouched.

### Re-execution and verification (2026-11-25)

The implementation and preceding execution record were already present when the plan was requested again. The lead inspected all implementation modules and tests, reproduced the 25 focused and 36 existing full tests, and reran both train/evaluation CLI pairs and `lake build`. Dependency validation with `.venv/Scripts/python.exe -m pip check` passed; the installed versions match the earlier environment record.

A fresh independent review by GPT-6.2 Sol High confirmed one helper-contract edge case: a final transition with both `terminated=True` and `truncated=True` could enter return memory. Although `ChainEnv` never emits both flags, the plan excludes every truncated episode. `index_completed_episode` now explicitly excludes a truncated final transition, and two regression cases verify that truncated episodes preserve existing memory regardless of the termination flag. DDQN termination masking is unchanged.

Lead final checks for this execution:
- `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --basetemp runs/revalidation-final-pytest`: **38 passed**.
- Both documented train/evaluation command pairs, with output directories `runs/revalidation/retrieval` and `runs/revalidation/baseline`: exactly reproduced every metric in the workflow table after the fix. These directories contain the new checkpoints and training metrics.
- `lake build`: passed, 4 jobs. No Lean source changes were needed.

The independent reviewer confirmed the fix with **38 passing full-suite tests** (`--basetemp runs/revalidation-review-final-pytest`) and **28 passing focused cases**. Separate checks passed 384 scalar DDQN examples, optimizer-step synchronization and JSON parity, checkpoint cutoff exclusion/admission and frozen evaluation, 400 randomized retrieval/reference comparisons, and 80 FIFO JSON round trips. No remaining in-scope findings. The final `git diff --check` passed.

The synthetic-task scope and performance limitations above still apply.
