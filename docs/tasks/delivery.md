# delivery: executable tasks

Status: offline delivery complete; D05 live-provider smoke remains blocked by credentials.
Requirements: [proposal](../proposal.md). Interfaces: [detailed design](../detailed-design.md).
Assignment and shared-file policy: [master plan](../../RETRIEVAL_DDQN_PLAN.md).

- Owner role: GPT-6.2 Sol Medium; coordinator integrates shared files; Astra High documents/reviews.
- Prerequisites: F for initial CLI; all modules for G6.
- Exclusive edit scope: `src/ai4algebra/cli.py`, `src/ai4algebra/__main__.py`, `tests/unit/test_cli.py`, `tests/integration/`. Coordinator owns README, pyproject entry points, CI and shared configs.
- Focused validation: `uv run pytest -q tests/unit/test_cli.py tests/integration`.
- Also run Ruff and mypy on the owned code/tests. Full gates are in [progress](progress.md).

Each checkbox is one independently reviewable change. Add the executed command, result,
and artifact path under the item when completing it. Mocks cannot satisfy a real-Lean gate.

- [x] **D01 — Expose CLI commands for corpus checks, solve, verify, train and evaluate.** Acceptance: Help/schema stable after contract handoff; commands have fake-provider tests and explicit output paths.

- [x] **D02 — Write beginner quickstart and environment configuration instructions.** Acceptance: Explain elementary tasks, Stacks migration, proof meaning, API budget and local key entry without secret printing.

- [x] **D03 — Add isolated end-to-end fixture with replayable proof artifact.** Acceptance: Clean-checkout command executes real Lean with deterministic provider and reports independently verified proof.

- [x] **D04 — Wire required offline Python and real-Lean CI jobs.** Acceptance: pytest, mypy strict, Ruff check/format and lake build required; no silent skip of missing Lean.

- [ ] **D05 — Run configured paid-provider smoke only after credentials/budget exist.** Acceptance: Otherwise record external blocker while offline suite passes; no unauthorized charges or fabricated online evidence.

- [x] **D06 — Commission independent correctness/leakage review and fix confirmed findings.** Acceptance: Reviewer reads combined code and runs negative tests; lead reruns impacted gates.

- [x] **D07 — Update all task checklists and final evidence.** Acceptance: Only checked tasks with executed evidence; preserve synthetic history; report incomplete modules truthfully.

## Handoff

Return changed files, contract changes (if any), exact test commands/results, artifact paths,
known limitations and unresolved blockers. Do not edit another owner's files or mark other
modules complete. The coordinator integrates shared config changes and updates progress.


## Live-provider blocker (2026-11-25)

D05 is blocked: a presence-only check found no configured `OPENAI_API_KEY` in the process environment or local `.env`. No credential value was printed, copied or serialized, and no paid request was attempted. All offline implementation and evaluation work continues. The configured runtime remains gpt-6.2-astra/high with the USD 1.00 whole-run cap.

## Offline delivery evidence (2026-11-25)

D02: README documents pinned build/setup, actual elementary solve/replay commands, local key entry, offline override, shared run ledger and later Stacks scope. Main executed the ring CLI command and separate verify command successfully.

D03: real CLI fixture passed in implementer integration checks (8 unit/integration cases in 47.95s); Main independently produced and replayed `runs/elementary-ring-smoke/result/certificate.json`, with accepted verdict at `runs/elementary-ring-replay/verdict.json`.

D04: `.github/workflows/lean_action_ci.yml` now builds the pinned Lean targets and requires pytest including real Lean tests, strict mypy and Ruff lint/format. This records workflow wiring and local evidence, not an unobserved remote CI result.

D01 acceptance: Main ran `python -m pytest -q -p no:cacheprovider tests/unit/test_cli.py tests/unit/test_evaluation.py`: **12 passed in 2.09s**. All five commands are available; actual corpus-check, solve, verify and train have executed successfully. Independent review confirmed strict source/plan compatibility, scoped output writer leases, and no output mutation from a rejected paid preflight.

D06 acceptance: independent code review reproduced and closed credential serialization, delayed dispatch, prompt display leakage, equal-goal branch pruning, late cancellation success, stale source compatibility, successor-feature substitution, policy-label mismatch, concurrent output corruption, Stacks scope omission and Git environment findings. Latest forward-first training-derived ordering passed independent 45-case review. Main final current-source checks: **326 non-Lean tests passed in 16.02s; 22 real Lean/integration tests passed in 417.55s; no skips with the official checkout configured**. Strict mypy and Ruff lint/format passed across 80 files. Locked uv sync and native Lean build passed.

D07 acceptance: all module checklists and the master coverage table now reflect the verified implementation, final source-frozen runs and exact test evidence. README includes offline solve/replay/train/evaluate commands, sanitized Lean configs, Stacks source scope and license notices. Final current-source code digest is recorded in progress.md. D05 remains explicitly unchecked; missing credentials are not reported as a passed live test.
