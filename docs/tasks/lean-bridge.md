# lean-bridge: executable tasks

Status: implemented; focused unit/real-process tests and static checks pass. Full proof certification is a separate module.
Requirements: [proposal](../proposal.md). Interfaces: [detailed design](../detailed-design.md).
Assignment and shared-file policy: [master plan](../../RETRIEVAL_DDQN_PLAN.md).

- Owner role: GPT-6.2 Sol High; GPT-6.2 Astra High for complex failures.
- Prerequisites: F02; use standalone elementary fixtures while corpus work continues.
- Exclusive edit scope: `src/ai4algebra/lean_bridge/`, `AI4Algebra/Bridge/`, `tests/unit/test_lean_protocol.py`, `tests/lean/test_bridge.py`. Coordinator owns lakefile/root imports.
- Focused validation: `uv run pytest -q tests/unit/test_lean_protocol.py tests/lean/test_bridge.py`.
- Also run Ruff and mypy on the owned code/tests. Full gates are in [progress](progress.md).

Each checkbox is one independently reviewable change. Add the executed command, result,
and artifact path under the item when completing it. Mocks cannot satisfy a real-Lean gate.

- [x] **L01 — Prove the JSON/proof-state protocol on the pinned Lean version.** Acceptance: Real spike observes initial goals, executes one valid tactic and rejects one invalid tactic; record exact versions before fixing backend design.

- [x] **L02 — Implement typed requests/responses and bounded subprocess handling.** Acceptance: Check framing, request IDs, schema, output size, exit status, timeout and crash cleanup using fake subprocess tests.

- [x] **L03 — Create sessions from immutable imports and statement hashes.** Acceptance: Return all ordered goals, local hypothesis IDs/types and snapshot identity; no user-controlled arbitrary commands.

- [x] **L04 — Implement replay-prefix snapshots and isolated branch stepping.** Acceptance: A failed tactic leaves parent intact; two child branches can replay independently with identical parent context.

- [x] **L05 — Export all subgoals and unresolved obligations after a tactic.** Acceptance: Multi-goal fixtures prevent accidental success on only the focused goal; returned state reflects Lean's actual result.

- [x] **L06 — Recover last verified states after timeout/crash and distinguish infrastructure loss.** Acceptance: Missing observations never masquerade as terminal success or valid bootstrapping states; sessions clean up.

- [x] **L07 — Integrate bridge build/test into a required Lean job.** Acceptance: Default lake build includes bridge targets; do not rely on currently unimported AI4Algebra/Test.lean.

## Handoff

Return changed files, contract changes (if any), exact test commands/results, artifact paths,
known limitations and unresolved blockers. Do not edit another owner's files or mark other
modules complete. The coordinator integrates shared config changes and updates progress.


## Evidence

24 protocol tests passed, including controlled subprocess timeout/output-limit cleanup, replay divergence and pin mismatch. Real pinned Mathlib open/reject/close and nonfirst-goal branching passed; aggregate pre-reader-hardening run passed 25 cases, final reader change passed 24 unit cases plus fresh real smoke. Default lake build passed 5 jobs. Root imports the observer, and required CI now runs pytest (including real Lean tests), mypy and Ruff. No remote CI run is claimed. Cold Windows replay is slow; default step limit calibrated to 60 seconds. Recovery after forced failure of a real Lean process has not been separately exercised; controlled workers cover the recovery logic.

Real recovery follow-up: `tests/lean/test_bridge.py::test_real_worker_timeout_recovers_parent` forced a real worker timeout, re-observed the unchanged parent in a fresh process, and completed a retry. This supersedes the earlier recovery limitation above. Native observer/verifier build now contains 13 jobs; direct native startup reduced measured replay overhead. Main also reproduced 29 protocol tests after adding raw-frame size and finite-timeout guards.

- [x] Share the native Lake environment across observers and verifiers within a run.
  Keep a fresh Lean process for each frame and recheck project input timestamps and
  the relevant parent environment before using cached paths. The focused protocol
  and CLI suite passed 42 tests.
