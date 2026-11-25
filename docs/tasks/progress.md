# AI4Algebra progress

Updated: 2026-11-25. Master: [task assignment plan](../../RETRIEVAL_DDQN_PLAN.md).
A checked box means delivered/verified, not merely described in the design.

Latest scope: offline proof training is now the default; optional paid smoke D05 is
deferred. The percentage below describes the original 79 assignments only. The new
[retrieval API extension](retrieval-api.md) and larger proof benchmark are separate
work; see [configuration and benchmark interpretation](../retrieval-api-benchmark.md).

### Retrieval API extension accepted, 2026-11-25

- Added a separate opt-in `python -m ai4algebra.api_benchmark` command, nine
  fixed queries, and `.env`/`.env.example` endpoint and request-limit settings.
  Preserved credentials; local defaults now use offline deterministic proposals.
- Implemented keyless LeanExplore/Loogle search and a disabled-by-default Stacks
  statement-only adapter. Stacks live use awaits its documented maintainer coordination.
  Public search results are not automatically admitted to the proof pipeline.
- Dry run: nine skips, zero requests. Final live run: 6/6 successful nonempty
  LeanExplore/Loogle responses, 0/6 exact expected-name hits at five, three disabled
  Stacks cases. See [recorded results](../retrieval-api-benchmark.md#recorded-smoke-run).
- Validation: 367 non-Lean tests passed; 22 Lean tests deliberately deselected for
  this isolated Python extension. Strict mypy, Ruff lint and formatting passed for
  88 files. Independent review reproduced 41 focused tests and static checks with
  no blockers. The prior 22 real-Lean successes remain historical evidence, not reruns.
- Preserved all existing frozen experiment artifacts. Source digests change with
  this addition; prior checkpoints must not be relabeled as current-source runs.
  Broader proof-corpus expansion and learned retrieval gains remain future work.

**Current acceptance: 78/79 assigned tasks (98.7%); 1/79 (1.3%) remains open.**
All offline implementation, training/evaluation, tests and independent reviews are complete.
D05 live-provider smoke is blocked by an absent local `OPENAI_API_KEY`; G6 therefore
remains pending. No paid API request was made. This is checklist completion, not a
forecast of time or general theorem-proving success.

## Documentation and prior work

- [x] Confirm elementary groups/rings before Stacks, curated statements before automatic translation.
- [x] Record development-agent models and runtime gpt-6.2-astra/high with USD 1.00/run cap.
- [x] Write [requirements](../proposal.md), [detailed design](../detailed-design.md) and master assignment plan.
- [x] Create 12 module task files containing 79 executable implementation tasks.
- [x] Create [autonomous implementation prompt](../prompt.md).
- [x] Create ignored local .env and blank-key .env.example; no paid calls made.
- [x] Preserve [completed synthetic baseline and validation evidence](../history/retrieval-ddqn-synthetic-baseline.md).
- [x] Independent review of the new documentation and cross-file consistency checks; staging fixes resolved and no blocking findings remain.

## Implementation modules

Implementation includes real Lean search, verification, candidate-aware training and
frozen elementary/Stacks evaluation. No module is complete until its checks and integration are reproduced.
The old synthetic baseline is not a completed Lean module.

- [x] [foundation](foundation.md) — F01–F07; 7 tasks.
- [x] [corpus](corpus.md) — C01–C07; 7 tasks.
- [x] [formalization](formalization.md) — FM01–FM06; 6 tasks.
- [x] [lean-bridge](lean-bridge.md) — L01–L07; 7 tasks.
- [x] [representation](representation.md) — E01–E05; 5 tasks.
- [x] [candidates](candidates.md) — A01–A08; 8 tasks.
- [x] [search](search.md) — S01–S07; 7 tasks.
- [x] [verification](verification.md) — V01–V06; 6 tasks.
- [x] [memory](memory.md) — M01–M06; 6 tasks.
- [x] [learning](learning.md) — Q01–Q07; 7 tasks.
- [x] [evaluation](evaluation.md) — B01–B06; 6 tasks.
- [ ] [delivery](delivery.md) — D01–D07; 7 tasks.

## Milestone gates

- [x] G0 — uv/typing/lint foundations and contracts.
- [x] G1 — real Lean protocol, branching, goals and failure recovery.
- [x] G2 — original-statement replay, axiom and dependency audit.
- [x] G3 — elementary closed proof loop and baseline search.
- [x] G4 — candidate-aware DDQN, causal memory and frozen evaluation.
- [x] G5 — curated Stacks pilot with provenance and splits.
- [ ] G6 — complete checks, reproducible CLI artifacts and independent code review.

## Execution log

| Date | Assignment | State | Evidence / blocker |
|---|---|---|---|
| 2026-11-25 | Synthetic baseline (prior scope) | Complete | 38 pytest cases, both train/eval smoke modes and lake build; archived record |
| 2026-11-25 | Requirements clarification | Complete | D1/D2/D3 and development roles captured from explicit user replies |
| 2026-11-25 | New document set | Complete | Independent Astra High review; 79 unique unchecked implementation tasks, valid local links, matched Lean pins and ignored .env; no runtime changes |
| 2026-11-25 | Review corrections | Complete | G3/G4 ordering, elementary evaluation dependencies, explicit Stacks train/validation/test gate and parent-frontier retention reconciled |

## Operational notes

Active ownership: foundation contracts and baseline typing returned and passed independent
review. foundation_impl now owns src/ai4algebra/representation and its tests; baseline_quality
owns src/ai4algebra/memory and its tests; lean_spike owns AI4Algebra/Bridge,
src/ai4algebra/lean_bridge and bridge tests. Main owns shared dependency/build/config files.

uv 0.13.10 created uv.lock. Syncing the existing .venv failed with Windows Access Denied
on an old package metadata directory. A separate ignored .venv-uv synced successfully with
`$env:UV_PROJECT_ENVIRONMENT = '.venv-uv'; .\.venv\Scripts\uv.exe sync --locked --group dev --extra test`.
Use .venv-uv/Scripts/python.exe for current validation; no old environment was deleted.

No unresolved product questions remain from discovery. Credentials must be supplied locally
before live-provider runs; no paid calls were made. The redacted configuration loader is
implemented. The durable run budget ledger/provider remain future work. No credentials
should appear in this log.

Main records each worker's reserved paths, current task ID, exact commands, outcomes,
artifacts, findings and blocker dependencies here. Missing external credentials are reported,
not worked around. A task may be completed only after its acceptance evidence is reproduced.


## Foundation validation (2026-11-25)

F01?F06 passed: 127 tests, strict mypy and Ruff across 18 files. Independent Sol High
review verified all reported foundation fixes and a fresh offline locked install.
Default lake build passed 5 jobs including AI4Algebra.Bridge.Main; real bridge tests
remain in progress. Foundation as a whole and G0 remain unchecked pending F07.

The first .venv-uv environment also hit metadata permissions on reinstall. Final working
environment: `%LOCALAPPDATA%/AI4Algebra/venv-copy`, with uv link-mode=copy. A repeated
locked sync succeeded. Python code moved to src/ai4algebra; Lean remains AI4Algebra.

## Active integration review

Representation passed 17 focused tests; memory passed 11 initial tests. Neither module is
marked complete: independent review requested historical-cutoff safety after FIFO eviction,
idempotent branch publication, stronger feature provenance integrity, certificate/verdict
binding, and publication metadata consistency after restore. Corrections are in progress.
The candidate-aware learner is being implemented against these typed interfaces.
Real Lean tests passed open/reject/close and focused branching; a final hardening rerun is
in progress. Default step timeout was calibrated to 60 seconds after measured cold starts.

## Status estimate

Final checklist acceptance is **78/79 (98.7%)**, with D05 (1.3% by task count) blocked
on a local API credential. Earlier percentage estimates were interim engineering
estimates during integration. Neither these percentages nor successful smoke cases
measure general proof-search capability. All subsequent entries below record the
chronological implementation and validation history.

Accepted-module consolidated check: 197 selected non-Lean tests passed; strict mypy passed across 27 source files. Bridge real-process evidence is recorded in lean-bridge.md. G2 and later gates remain open.

G1 remains pending one explicit real-process timeout-and-recovery test; controlled-worker recovery and real replay tests pass separately. The bridge owner is adding that combined check.

## Latest handoffs

The explicit real Lean timeout/recovery gate passed: the worker was timed out, the original
parent was re-observed in a fresh process, and a retry completed. G1 is now checked.
Verifier owner reports 22 unit and 9 real audit tests passed, including forbidden axioms,
indirect sorry, held-out dependency wrappers and mismatched elaborated types. Independent
verification review and final integration remain pending.

Active assignments: lean_spike is compiling/benchmarking native workers after verifier
implementation; elementary_corpus owns corpus/formalization fixtures; proof_learning now
owns candidates and the paid-provider budget guard. Learning review fixes are delivered
with exact collected encodings for replay, but real training Q06 is not implemented yet.

## Verified elementary search and current integration

Autonomous deterministic search proved `a * (b * b⁻¹) = a` in a group using two typed
actions: `simp only [mul_inv_cancel]`, then `exact mul_one a`. The archived run took
27.926 seconds with two applicability probes reused as action results, one independent
verifier invocation and zero paid-provider requests. Replay, exact theorem type, axiom
and dependency checks all passed. Artifacts: `runs/elementary-search-smoke/proof.lean`,
`certificate.json`, `verdict.json`, and `search.json`. This is one smoke case, not a
benchmark success-rate estimate or evidence of learned search performance.

The corpus worker also verified all four curated elementary certificates; their
preselected tactic paths are distinct evidence from autonomous discovery. Main reproduced
the corpus/formalization suite after the protected-source-path correction:
`python -m pytest -q tests/unit/test_corpus.py tests/unit/test_formalization.py tests/lean/test_statements.py`
using `%LOCALAPPDATA%/AI4Algebra/venv-copy/Scripts/python.exe`: **35 passed in 12.55s**.
The only warning was OneDrive denying pytest cache writes; subsequent checks disable that
optional cache. Tests exercised real Windows junction aliases without skips.

Current reservations: proof_learning owns training/evaluation/CLI integration and tests;
proof_search owns search and its tests, plus the coordinated generation-prefix flag;
lean_spike owns bridge request accounting (including recovery work) and bridge/verifier
tests. Main owns shared docs/config/build/CI and acceptance validation. No paid API calls
have been made. Live-provider acceptance and Stacks training/testing are still open.

## Elementary closed-loop gate accepted

G2/G3 accepted after independent review and Main reproduction of **99 focused unit tests**. Two autonomous deterministic examples now exist: group inverse cancellation (`runs/elementary-search-smoke`) and ring distributivity over subtraction/addition (`runs/elementary-ring-smoke/result`). The ring proof used `simp only [mul_add]` then `simp only [mul_sub]`, two charged probes and one audit, 35.59s, zero API calls. Main separately replayed the exported certificate through `python -m ai4algebra verify --offline`; audit accepted. These are tiny smoke cases, not evidence of a learned-policy advantage.

Active reservations now: elementary_corpus owns pinned Stacks importer/mappings/pilot; proof_learning owns training/evaluation/CLI integration and token accounting; foundation_review independently reviews the integrated training/evaluation flow. Search/provider findings are corrected and independently rechecked. D05 live API validation is blocked by absent local credentials; all offline work continues.

## Current-source elementary training

Q06 accepted: two independent seeds in `runs/elementary-experiment-{7,11}` each completed two verified episodes and four optimizer updates; Main loaded both frozen checkpoints against the current catalog and code digest. G4 still awaits held-out comparisons. Full configured pytest is running; locked sync, native Lean build, strict mypy across 80 Python files, Ruff lint and format have passed.

## Pinned source and full-suite validation

C/FM completed after independent Stacks review and Main reproduction. Official pin `a04446e57ec1fbc252a871afcec7752fb2807b14`; selection has 9 reviewed tags, 6 exclusions, 2 full mappings and 1 image-only subclaim. Three curated typed certificates pass complete audit; the bounded dependency ceiling is now 8,192 after independently measuring the largest closure at 4,912 declarations. No truncated dependency walk is accepted.

Main `AI4ALGEBRA_TEST_STACKS_CHECKOUT=<pinned checkout> python -m pytest -q -p no:cacheprovider`: **348 passed in 406.75s, no skips**. Strict mypy, Ruff lint/format and locked/native builds passed. After that test process started, a TRAIN-only rollout exposed an immediate inverse-rewrite cycle. A small forward-first ordering correction preserves reverse choices and passed independent 45-test re-review. Affected source-frozen training/evaluation evidence is being regenerated; prior experiments remain historical rather than silently relabeled.

## Final current-source validation

After the last candidate ordering correction, Main reran the complete test partition: **326 non-Lean tests passed in 16.02s and 22 real Lean/integration tests passed in 417.55s** (348 total, zero skips with the pinned upstream checkout configured). Strict mypy and Ruff lint/format passed all 80 Python files. D06 independent review is accepted with all confirmed findings corrected. Source-frozen real evaluations remain in flight; no further source changes or tuning are planned.

## Final elementary frozen comparison

G4 and B01?B05 accepted. Current inputs `runs/elementary-release-{7,11}` each have two verified train episodes, four collected transitions, four return entries and four optimizer updates. Validation and test reports `runs/elementary-release-{validation,test}` each verified 6/6 trials across two seeds and three modes on **one theorem per split**. Main checked current source/catalog/training identities and 48 proof/trace hashes; the orchestration confirmed all 34 frozen training files unchanged. All methods used identical limits; no held-out retrieval hits or performance advantage were observed. Stacks held-out results are still running.

## Final accepted release evidence

Final code digest: `9cc5ec6a623602388c07250c0f4b207616f2006c92c8c86833b4a3c99e33baa6`.

- Elementary: `runs/elementary-release-{7,11}`; both seeds trained on two verified episodes with four updates. `runs/elementary-release-{validation,test}/evaluation.json` each has one task, two seeds and three modes: 6/6 verified trials, 1/1 in each row. All 34 training files remained unchanged.
- Stacks: `runs/stacks-pilot-experiment-7` trained on the independently verified 00E5 image subclaim, three transitions and two updates. `runs/stacks-pilot-experiment-{validation,test}/evaluation.json` each reports 0/1 per mode on the full mapped held-out task after exhausting the fixed probe budget. All 12 training files remained unchanged. No full-tag proof credit is assigned to the training subclaim.
- Main checked final current-source checkpoint identities, both catalogs and the elementary proof/trace hashes plus all Stacks held-out trace hashes. Every successful trial has an independently accepted certificate; unsuccessful Stacks trials have no selected certificate. No performance advantage or generalization claim follows from this pilot.
- Final checks: 326 non-Lean plus 22 real Lean/integration tests passed (348 total, zero skips with the source checkout configured); strict mypy and Ruff lint/format passed all 80 Python files; locked uv sync and native Lean build passed.
- All confirmed independent review findings were corrected and rechecked. D07 records this final evidence and the remaining external blocker. No commits or pushes were made; user source/assets/Papers changes were preserved.

D05 remains open after a final presence-only credential check found no key. Fill `OPENAI_API_KEY` locally in the ignored `.env` to permit the already-authorized gpt-6.2-astra/high live smoke under the shared USD 1.00 run cap. No secret value was printed or copied to agents.
