# learning: executable tasks

Status: implemented; real verified rollout training and frozen checkpoint loading validated.
Requirements: [proposal](../proposal.md). Interfaces: [detailed design](../detailed-design.md).
Assignment and shared-file policy: [master plan](../../RETRIEVAL_DDQN_PLAN.md).

- Owner role: GPT-6.2 Sol High.
- Prerequisites: F02, E, M; integrate after deterministic loop G3.
- Exclusive edit scope: `src/ai4algebra/learning/`, `src/ai4algebra/training/`, `tests/unit/test_proof_ddqn.py`. Existing `retrieval_ddqn/` remains under coordinator ownership.
- Focused validation: `uv run pytest -q tests/unit/test_proof_ddqn.py tests/test_learner.py tests/test_retrieval.py tests/test_integration.py`.
- Also run Ruff and mypy on the owned code/tests. Full gates are in [progress](progress.md).

Each checkbox is one independently reviewable change. Add the executed command, result,
and artifact path under the item when completing it. Mocks cannot satisfy a real-Lean gate.

- [x] **Q01 — Implement shared scalar Q(state,candidate) network for variable action sets.** Acceptance: Permutation/padding tests preserve semantic action scores; do not reuse fixed left/right output indices as tactics.

- [x] **Q02 — Implement masked Double DQN targets over stored next candidate features.** Acceptance: Online selects eligible action, target evaluates it; differing-argmax exact numerical fixture; no retrieval inside Bellman target.

- [x] **Q03 — Handle termination, observed truncation and missing next actions explicitly.** Acceptance: Terminal reward-only; valid truncation bootstraps from actual final state; no candidate-generation miss silently treated as proven dead-end.

- [x] **Q04 — Implement selected-action loss/gradients and hard target synchronization.** Acceptance: Finite differences, detached target, exact initial copy and optimizer-step sync tests.

- [x] **Q05 — Blend causal compatible retrieval values only for action selection.** Acceptance: Unmatched fallback exact; epsilon applied after blend; candidate-ID changes cannot redirect old returns.

- [x] **Q06 — Train only after verified trajectories are available.** Acceptance: Record fixed step/Lean-call budgets, seeds and all transition filters; offline tiny-corpus smoke.

- [x] **Q07 — Save versioned evaluation checkpoints with encoder/candidate/corpus metadata.** Acceptance: Frozen reload reproduces next scores/targets; reject incompatible artifacts; do not claim resumable training without replay/RNG/session persistence.

## Handoff

Return changed files, contract changes (if any), exact test commands/results, artifact paths,
known limitations and unresolved blockers. Do not edit another owner's files or mark other
modules complete. The coordinator integrates shared config changes and updates progress.


## Accepted learner evidence (2026-11-25)

Main reproduced `python -m pytest -q -p no:cacheprovider tests/unit/test_proof_ddqn.py tests/unit/test_memory.py tests/unit/test_representation.py`: **46 passed in 1.14s**. Earlier independent review verified strict transition/schema validation, frozen checkpoint compatibility, and exact collected feature/context binding. Q06 remains open until real rollouts, optimization and frozen evaluation artifacts are accepted.

## Real training acceptance

Final current-source runs: `runs/elementary-release-7` and `runs/elementary-release-11`. Each completed two independently verified train episodes, collected four transitions, retained four verified returns at cutoff 6, and performed four optimizer updates. Main loaded both through `load_training` against a fresh current catalog and code digest. Checkpoint hashes: seed 7 `3dafb70883f1f6c6fe54d2a5d33808996ef3b242e6ea27bbe29a7d6756dc76f8`; seed 11 `9c005f5d974df26c08fe8146e9739240897c75a53f5c63acf7f210927835f41a`. Earlier `elementary-experiment-*` and other run directories are historical development evidence, not the final source-frozen comparison.

Both validation and test evaluations verified all six seed/policy trials on their respective one-task split; no learned or retrieval advantage is established. See evaluation.md for denominators, immutable-input checks and artifacts.
