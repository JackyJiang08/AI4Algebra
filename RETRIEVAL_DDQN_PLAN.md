# AI4Algebra: Lean proof-search task assignment plan

Updated: 2026-11-25. Scope: requirements, design and executable implementation assignments
for the missing Lean proof-search loop. **79 of 79 assignments are accepted.** D05 now has a live Astra proposal,
a verified proof and separate offline replay. This is the original milestone's checklist, not a
completion percentage for the new benchmark expansion. The latest user request
authorizes paid proposals with a USD 0.50 per-turn cap and one shared run/ledger.
Live smoke evidence is recorded in the delivery checklist and progress log.

New phase: [external retrieval benchmarks](docs/retrieval-api-benchmark.md) for
Stacks Project, LeanExplore and Loogle, followed by a larger and more varied offline
proof corpus. Endpoint settings belong in `.env`; benchmark queries and results are
separate artifacts. See [extension assignments](docs/tasks/retrieval-api.md).

## 1. Authoritative inputs and outputs

- User workflow: [prompt.md](prompt.md).
- Target procedure: [assets/mermaid-diagram.png](assets/mermaid-diagram.png).
- Requirements and decisions: [docs/proposal.md](docs/proposal.md).
- Module interfaces and algorithms: [docs/detailed-design.md](docs/detailed-design.md).
- Small executable tasks: [docs/tasks/](docs/tasks/progress.md), one file per module.
- Autonomous implementation starting prompt: [docs/prompt.md](docs/prompt.md).
- Prior completed synthetic work: [archived plan/evidence](docs/history/retrieval-ddqn-synthetic-baseline.md).

The explicit user decisions in the proposal take precedence over old synthetic-only scope.
The proposal defines outcomes, the detailed design defines interfaces, and per-module
checklists define implementation steps. Changes to one must be reconciled with the others.
Do not interpret the archived statement “all assignments complete” as completion of this plan.

## 2. Confirmed scope

1. Begin with elementary **group and ring exercises**.
2. Use **curated Lean statements** first; automatic informal-to-Lean translation is later work.
3. Add Stacks Project theorem training/testing **after the elementary loop works**.
4. Paid generation is authorized using OpenAI **gpt-6.2-astra**, reasoning **high**,
   maximum **USD 0.50 per assistant turn**, across tasks, retries and workers sharing
   one durable run/ledger. Offline operation remains available without a key.
5. Development roles: **GPT-6.2 Astra High** for documentation and difficult debugging;
   **GPT-6.2 Astra Medium/Low** for coordination; **GPT-6.2 Sol High/Medium**
   for implementation/testing.
6. After requirements are settled, Main Agent delegates modules, integrates results,
   runs checks, fixes issues and updates progress without routine human intervention.
7. Mandatory quality gates: pytest unit/integration tests, strict mypy, Ruff, real Lean checks.

These choices were explicitly answered by the user. The model's OpenAI API identifier is
documented [here](https://developers.openai.com/api/docs/models/gpt-6.2-astra).
The USD 0.50 limit concerns application tactic-generation API usage, not development-agent billing.

## 3. Starting state and preservation

This section records the pre-implementation baseline. For current implementation and
validation evidence, use the coverage table below and [progress](docs/tasks/progress.md).

Completed: the separate NumPy synthetic chain experiment, with 38 passing tests, DDQN,
replay, causal return retrieval, checkpoints and frozen evaluation. The latest recorded
Lean project build passed. Preserve these as regression coverage.

Missing: live Lean state extraction/execution, mathematical state/action representations,
applicable-lemma retrieval, tactic generation, proof-tree search, original-statement replay,
axiom/dependency audit, real-theorem learning and evaluation.

The current Lean root imports only Basic.lean, so its successful build does not prove that
Test.lean or any future bridge is tested. Add explicit required bridge/verification targets.
The current Python project has no uv.lock or mypy/Ruff configuration. Foundation tasks
establish the requested uv workflow. Do not overwrite the repository with uv init.

Preserve the user's Papers/, prompt.md and asset changes. Keep the original synthetic
execution record in docs/history. New proof-search Python code belongs in src/ai4algebra/;
the old retrieval_ddqn package remains runnable. No new runtime code is claimed by this rewrite.

## 4. Diagram coverage and acceptance

| Procedure block | Current state | Assigned completion |
|---|---|---|
| Lean goals, hypotheses, remaining depth | Implemented; real Lean observations and branch tests pass | L03–L06, S01/S04 |
| Encode proof state | Structural state/candidate features implemented and reviewed | E01–E05 |
| Retrieve accessible lemmas and instantiate tactics | Elementary and Stacks typed premises/probes implemented and reviewed | C/FM metadata, A01–A03/A07 |
| Score state-action pairs | Variable-candidate DDQN trained on verified trajectories; frozen evaluation complete | Q01–Q05 variable candidate scorer |
| Choose one tactic | Deterministic, DDQN and return-aware modes validated offline; live API smoke accepted | S02/S03, A04–A06 |
| Execute tactic in Lean | Implemented; timeout/recovery and branch tests pass | L01–L07 |
| Valid with goals remaining | Two-step autonomous group proof demonstrated | L04/L05, S03/S06 |
| All goals closed | Provisional closure followed by independent audit implemented | S05, V01–V06 |
| Replay proof and check axioms | Fresh replay, exact type, axiom and dependency checks pass | V01–V06 |
| Store transition and reward | Exact chronological samples, verified rewards and causal training memory validated | S04/S06, M01–M06 |
| Replay minibatch and DDQN update | Real elementary/Stacks rollout training, optimizer updates and frozen reload passed | Q02–Q07 |
| Real train/test workflow | CLI and both corpus workflows complete; honest held-out outcomes archived; live API smoke accepted | C03, FM, B01–B06, D01–D07 |

Current checklist acceptance: **79/79 (100%)**; D05 live-provider evidence is archived.
This counts assignments, not elapsed time or general theorem-proving capability. The
elementary held-out splits each verified 1/1 task in every seed/policy condition. The
Stacks training subclaim was verified; both full held-out Stacks tasks remained unsolved
within the fixed probe budget. No learned or retrieval advantage is established.
The autonomous elementary proof and its independent audit are archived in
[runs/elementary-search-smoke](runs/elementary-search-smoke/proof.lean).

## 5. Architecture rules shared before dispatch

- Typed immutable contracts; explicit schema versions, task/split identities and hashes.
- Separate three structures: source citation dependencies, typed premise/candidate records,
  and authoritative Lean proof-tree states. Keep return memory separate from lemma retrieval.
- The Lean bridge owns state truth. Use a pinned-toolchain spike before adopting its backend.
  A replay-prefix snapshot backend is the first implementation target; verify compatibility.
- Invalid candidates cannot mutate the parent. Observe all goals, hypotheses and unresolved
  obligations. No textual “no goals” heuristic substitutes for final proof checking.
- Curated theorem statements and allowed imports are immutable during a run.
- Candidate Q-values use **Q(state, candidate)**, with stable semantic candidate identity.
  A dynamic list position is not a global action identifier. Store next candidate sets/masks
  for replay. Do not graft tactics onto the synthetic two-output network.
- Online selects the eligible next candidate; target evaluates that same candidate.
  Retrieval never enters the Bellman target. Hard target copies count optimizer steps.
- Termination suppresses bootstrap; budget truncation bootstraps only with the actual final
  observation and defined next action set. Infrastructure failures with missing observations
  are excluded/reported. Candidate generation failure is not mathematical impossibility.
- Return memory accepts completed verified, non-truncated training branches only. Preserve
  original step/availability metadata, strict cutoff and same-episode exclusion.
- Every successful search result must survive fresh replay, exact statement identity,
  transitive axiom and forbidden-dependency checks. Provisional closure gets no success reward.
- Held-out proofs/equivalents must not leak through prompts, imports, simp/automation,
  retrieval, replay, shared caches or later theorem dependencies. Test this adversarially.
- Paid provider calls require a valid key and a pre-call conservative cost reservation.
  One durable USD 0.50 budget spans the entire run; uncertain charges retain reservations.
  No automatic budget increases or model substitutions.

## 6. Roles and ownership

| Role | Model/effort | Responsibility |
|---|---|---|
| Main coordinator | gpt-6.2-astra medium; low for clerical dispatch | Track dependency graph, contracts, ownership, integration, progress and evidence |
| Documentation architect | gpt-6.2-astra high | Requirements/design consistency and task quality |
| Module implementer | gpt-6.2-sol high for Lean/learning/complex modules; medium for bounded utilities | Implement assigned files and tests |
| Complex-debugging specialist | gpt-6.2-astra high | Diagnose confirmed hard failures; return fix within assigned scope |
| Independent reviewer | gpt-6.2-sol high for code/tests; gpt-6.2-astra high for design | Read-only review; no self-approval by an implementer |

Main owns shared files: this plan, README.md, docs/proposal.md, docs/prompt.md,
docs/tasks/progress.md, pyproject.toml, uv.lock, .gitignore, .env.example, lakefile.toml,
AI4Algebra.lean, shared configs and CI. Architectural documentation can be explicitly
reserved to the architect. Do not hand .env secret contents to workers.

Worker ownership is restricted to its module paths below. Shared-file changes are returned
as proposed patches for Main to integrate. Existing baseline edits needed for typing/lint
are serialized by Main; no concurrent worker touches retrieval_ddqn or its old tests.
Do not create nested subagents that exceed available slots or violate another reservation.
Run independent assignments concurrently only after their contracts are available.

### foundation

- Assignment: [foundation tasks](docs/tasks/foundation.md), F01–F07.
- Owner: GPT-6.2 Sol Medium.
- Dependency: None; runtime provider selection is settled.
- Files: `src/ai4algebra/config.py`, `src/ai4algebra/contracts.py`, `src/ai4algebra/__init__.py`, `tests/unit/test_config.py`, `tests/unit/test_contracts.py`. Coordinator owns `pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example` and shared CI files.
- Completion: every task checkbox has passing evidence, contracts remain compatible,
  and the coordinator reproduces focused checks: `uv run pytest -q tests/unit/test_config.py tests/unit/test_contracts.py`.

### corpus

- Assignment: [corpus tasks](docs/tasks/corpus.md), C01–C07.
- Owner: GPT-6.2 Sol Medium.
- Dependency: F02; Stacks portion after elementary milestone G3.
- Files: `src/ai4algebra/corpus/`, `data/manifests/`, `tests/unit/test_corpus.py`, `tests/unit/test_stacks.py`, `tests/fixtures/corpus/`. Formalization owns Lean theorem statements.
- Completion: every task checkbox has passing evidence, contracts remain compatible,
  and the coordinator reproduces focused checks: `uv run pytest -q tests/unit/test_corpus.py`.

### formalization

- Assignment: [formalization tasks](docs/tasks/formalization.md), FM01–FM06.
- Owner: GPT-6.2 Sol High; escalate difficult mathematical/debugging issues to GPT-6.2 Astra High.
- Dependency: F02, C01/C02, Lean bridge compatibility spike L01.
- Files: `src/ai4algebra/formalization/`, `AI4Algebra/Benchmarks/`, `data/formalizations/`, `tests/unit/test_formalization.py`, `tests/lean/test_statements.py`, `tests/lean/test_stacks_lean.py`. Coordinator integrates Lean root imports/build targets.
- Completion: every task checkbox has passing evidence, contracts remain compatible,
  and the coordinator reproduces focused checks: `uv run pytest -q tests/unit/test_formalization.py tests/lean/test_statements.py`.

### lean-bridge

- Assignment: [lean-bridge tasks](docs/tasks/lean-bridge.md), L01–L07.
- Owner: GPT-6.2 Sol High; GPT-6.2 Astra High for complex failures.
- Dependency: F02; use standalone elementary fixtures while corpus work continues.
- Files: `src/ai4algebra/lean_bridge/`, `AI4Algebra/Bridge/`, `tests/unit/test_lean_protocol.py`, `tests/lean/test_bridge.py`. Coordinator owns lakefile/root imports.
- Completion: every task checkbox has passing evidence, contracts remain compatible,
  and the coordinator reproduces focused checks: `uv run pytest -q tests/unit/test_lean_protocol.py tests/lean/test_bridge.py`.

### representation

- Assignment: [representation tasks](docs/tasks/representation.md), E01–E05.
- Owner: GPT-6.2 Sol Medium.
- Dependency: F02; fake observations allow work in parallel with L.
- Files: `src/ai4algebra/representation/`, `tests/unit/test_representation.py`.
- Completion: every task checkbox has passing evidence, contracts remain compatible,
  and the coordinator reproduces focused checks: `uv run pytest -q tests/unit/test_representation.py`.

### candidates

- Assignment: [candidates tasks](docs/tasks/candidates.md), A01–A08.
- Owner: GPT-6.2 Sol High.
- Dependency: F02, L01/L03, C03, FM04; D2 is settled.
- Files: `src/ai4algebra/candidates/`, `tests/unit/test_candidates.py`, `tests/unit/test_provider.py`, `tests/lean/test_applicability.py`.
- Completion: every task checkbox has passing evidence, contracts remain compatible,
  and the coordinator reproduces focused checks: `uv run pytest -q tests/unit/test_candidates.py tests/unit/test_provider.py tests/lean/test_applicability.py`.

### search

- Assignment: [search tasks](docs/tasks/search.md), S01–S07.
- Owner: GPT-6.2 Sol High.
- Dependency: L, E, A; V before claiming any success; start with fake interfaces.
- Files: `src/ai4algebra/search/`, `tests/unit/test_search.py`, `tests/lean/test_search_loop.py`.
- Completion: every task checkbox has passing evidence, contracts remain compatible,
  and the coordinator reproduces focused checks: `uv run pytest -q tests/unit/test_search.py tests/lean/test_search_loop.py`.

### verification

- Assignment: [verification tasks](docs/tasks/verification.md), V01–V06.
- Owner: GPT-6.2 Sol High.
- Dependency: F02, L01; independent of learner and model APIs.
- Files: `src/ai4algebra/verification/`, `AI4Algebra/Verification/`, `tests/unit/test_verification.py`, `tests/lean/test_proof_audit.py`.
- Completion: every task checkbox has passing evidence, contracts remain compatible,
  and the coordinator reproduces focused checks: `uv run pytest -q tests/unit/test_verification.py tests/lean/test_proof_audit.py`.

### memory

- Assignment: [memory tasks](docs/tasks/memory.md), M01–M06.
- Owner: GPT-6.2 Sol Medium.
- Dependency: F02, E; full publication integration after S/V.
- Files: `src/ai4algebra/memory/`, `tests/unit/test_memory.py`.
- Completion: every task checkbox has passing evidence, contracts remain compatible,
  and the coordinator reproduces focused checks: `uv run pytest -q tests/unit/test_memory.py`.

### learning

- Assignment: [learning tasks](docs/tasks/learning.md), Q01–Q07.
- Owner: GPT-6.2 Sol High.
- Dependency: F02, E, M; integrate after deterministic loop G3.
- Files: `src/ai4algebra/learning/`, `src/ai4algebra/training/`, `tests/unit/test_proof_ddqn.py`. Existing `retrieval_ddqn/` remains under coordinator ownership.
- Completion: every task checkbox has passing evidence, contracts remain compatible,
  and the coordinator reproduces focused checks: `uv run pytest -q tests/unit/test_proof_ddqn.py tests/test_learner.py tests/test_retrieval.py tests/test_integration.py`.

### evaluation

- Assignment: [evaluation tasks](docs/tasks/evaluation.md), B01–B06.
- Owner: GPT-6.2 Sol High.
- Dependency: B01–B05 use elementary C01–C03/C06, FM01–FM04 and V/S, plus Q for learned comparisons; B06 adds Stacks C04/C05/C07 and FM05/FM06, then reuses Q06 on Stacks train data.
- Files: `src/ai4algebra/evaluation/`, `tests/unit/test_evaluation.py`, `tests/integration/test_lean_cli.py`.
- Completion: every task checkbox has passing evidence, contracts remain compatible,
  and the coordinator reproduces focused checks: `uv run pytest -q tests/unit/test_evaluation.py tests/integration/test_lean_cli.py`.

### delivery

- Assignment: [delivery tasks](docs/tasks/delivery.md), D01–D07.
- Owner: GPT-6.2 Sol Medium; coordinator integrates shared files; Astra High documents/reviews.
- Dependency: F for initial CLI; all modules for G6.
- Files: `src/ai4algebra/cli.py`, `src/ai4algebra/__main__.py`, `tests/unit/test_cli.py`, `tests/integration/`. Coordinator owns README, pyproject entry points, CI and shared configs.
- Completion: every task checkbox has passing evidence, contracts remain compatible,
  and the coordinator reproduces focused checks: `uv run pytest -q tests/unit/test_cli.py tests/integration`.


## 7. Dependency-ordered execution

| Wave | Assignments | Exit condition |
|---|---|---|
| 0 | Foundation F01–F07, shared contract review, L01 spike | G0; protocol viable on pinned Lean |
| 1 | Elementary corpus/curation C01–C03/C06, FM01–FM04; bridge L02–L07; representation E | Contracts, real states and curated fixtures ready |
| 2 | Verification V, candidates A, fake-interface search tests S01/S02 | Real branch rollback, legal candidates, trusted verifier |
| 3 | Search S03–S07, memory M, deterministic delivery slice D01/D03 | G1/G2/G3: solve/verify, elementary run reports, train-split traces and replayable proofs |
| 4 | Learning Q, evaluation B01–B05, learned CLI slice D01, paid adapter smoke and budget tests | G4: train/evaluate commands, trained scorer and frozen held-out comparison |
| 5 | Stacks C04/C05/C07, FM05/FM06, reuse Q06, B06 | G5: train on curated Stacks train split, select on validation, freeze/test on disjoint held-out split; mapping, counts and checkpoint evidence required |
| 6 | Delivery D02/D04–D07 and independent review | G6: all required checks/evidence and resolved findings |

Wave rows describe readiness rather than unlimited parallelism. Where a task in a row
depends on another, dispatch in topological order. Mocked tests may start early but do not
satisfy real integration gates. Baseline search and verified traces precede reinforcement learning.

## 8. Stacks theorem policy

The user's preferred later source is [the Stacks Project](https://stacks.math.columbia.edu/).
Use [stable tags](https://stacks.math.columbia.edu/tags) and a pinned
[source repository snapshot](https://github.com/stacks/stacks-project), retaining provenance
and source license notices. Begin the later selection with feasible
[commutative algebra](https://stacks.math.columbia.edu/tag/00AO) results.

Each benchmark entry records tag/URL, source revision/hash, original statement, cited
dependencies, curated Lean type/imports/hash, mapping evidence, target aliases, and split.
Do not assert a tag-to-mathlib mapping without evidence. Separate source text/proofs from
runtime statements. Do not serve held-out proofs to the agent.

The [website API](https://stacks.math.columbia.edu/api) is documented as unstable and asks
users to contact maintainers. The plan uses source snapshots rather than depending on that
API, and does not authorize sending mail. No Stacks API credential is required by this design.

## 9. API key and run configuration

Created now: ignored .env and tracked-template .env.example. Required secret:
**OPENAI_API_KEY**, currently blank. Local Lean and public source acquisition need no key.
No unrelated service keys are required.

Runtime settings: openai; gpt-6.2-astra; high; https://api.openai.com/v1;
ALLOW_PAID_API=true; API_BUDGET_USD=1.00 (with AI4ALGEBRA_ prefixes as in the files).
The loader/provider and cost enforcement are future implementation tasks; the presence
of these files alone does not activate paid calls.

Use OpenAI Responses through a version-pinned SDK. Load credentials locally, redact them,
and never serialize them into reports/checkpoints. Price accounting includes reasoning
tokens and all billed requests, including retries. Record pricing version, pre-call bound,
reservation and actual usage. Disable unpriced request options; stale/unknown pricing
blocks new paid requests instead of risking the cap.

## 10. Required validation and proposed command surface

These are **future completion commands**, not claims that tools or new modules already exist:

```powershell
uv sync --locked --group dev --extra test
lake build
uv run pytest -q
uv run mypy --strict src/ai4algebra retrieval_ddqn tests
uv run ruff check src/ai4algebra retrieval_ddqn tests
uv run ruff format --check src/ai4algebra retrieval_ddqn tests
uv run pytest -q tests/lean tests/integration
```

Windows temporary-directory fallback: add `-p no:cacheprovider --basetemp runs/lean-loop-pytest`.
CI must exercise real Lean, not skip the job if Lean is unavailable. No API keys in default tests.

The delivery module will implement `python -m ai4algebra` with corpus checks, solve, verify,
train and evaluate commands. Final flags follow the detailed design and CLI handoff;
these new commands are not available today. Preserve the existing
`python -m retrieval_ddqn.train` / `evaluate` commands for regression checks.

Independent review covers: original-statement fidelity, all-goal accounting, invalid
branch rollback, axiom policy, dynamic action/mask targets, truncation, causal memory,
alias/transitive leakage, frozen evaluation, the USD 0.50 cap, secret handling and reproducibility.
Return prioritized findings with files/lines, repros, exact checks and limitations.
Main resolves confirmed findings and repeats affected validation before marking completion.

## 11. Definition of done and progress

Documentation delivered: requirements, detailed design, 12 module checklists with 79
executable tasks, progress tracker and autonomous implementation prompt; environment
template and preserved synthetic evidence.

Implementation is done only when every required module is complete, gates G0–G6 in the
proposal pass, task evidence is recorded and independent review has no unresolved blockers.
No new Lean-loop task is marked complete merely because this plan was written.
Track live state in [docs/tasks/progress.md](docs/tasks/progress.md).

Documentation verification for this rewrite: independent GPT-6.2 Astra High review found
no remaining blocking issues after staging/dependency corrections. All local Markdown
file links resolve, all 79 implementation task IDs are unique and unchecked, toolchain
pins match the repository, and Git ignores .env while permitting .env.example. Runtime
tests were not rerun for this documentation/configuration-only change. The prior 38-test
record remains historical evidence for the unchanged synthetic implementation.
