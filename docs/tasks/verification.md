# verification: executable tasks

Status: implemented and independently reviewed; focused checks reproduced by Main.
Requirements: [proposal](../proposal.md). Interfaces: [detailed design](../detailed-design.md).
Assignment and shared-file policy: [master plan](../../RETRIEVAL_DDQN_PLAN.md).

- Owner role: GPT-6.2 Sol High.
- Prerequisites: F02, L01; independent of learner and model APIs.
- Exclusive edit scope: `src/ai4algebra/verification/`, `AI4Algebra/Verification/`, `tests/unit/test_verification.py`, `tests/lean/test_proof_audit.py`.
- Focused validation: `uv run pytest -q tests/unit/test_verification.py tests/lean/test_proof_audit.py`.
- Also run Ruff and mypy on the owned code/tests. Full gates are in [progress](progress.md).

Each checkbox is one independently reviewable change. Add the executed command, result,
and artifact path under the item when completing it. Mocks cannot satisfy a real-Lean gate.

- [x] **V01 — Reconstruct a standalone theorem from trusted manifest and selected tactics.** Acceptance: Ignore candidate-supplied declarations/imports; preserve original type and hypotheses exactly.

- [x] **V02 — Replay in a fresh bounded Lean process.** Acceptance: Verify all goals/metavariables closed and the expected declaration exists; process exit success alone is insufficient.

- [x] **V03 — Collect transitive axioms from the final proof declaration.** Acceptance: Reject sorryAx and every axiom outside the explicit versioned allowlist; fixture for hidden indirect sorry.

- [x] **V04 — Audit direct/transitive theorem dependencies against task policy.** Acceptance: Reject self-reference, gold module imports, target aliases and held-out answer dependencies, including automation-mediated use.

- [x] **V05 — Produce a certificate bound to source/type/proof/environment hashes.** Acceptance: Detect artifact modification and incompatible toolchain; expose readable rejection reasons.

- [x] **V06 — Test adversarial and valid proofs.** Acceptance: Cover admit/sorry, changed assumptions, false type substitution, added axiom, incomplete proof, valid classical proof and clean multi-step proof.

## Handoff

Return changed files, contract changes (if any), exact test commands/results, artifact paths,
known limitations and unresolved blockers. Do not edit another owner's files or mark other
modules complete. The coordinator integrates shared config changes and updates progress.


## Accepted evidence (2026-11-25)

Main reproduced `python -m pytest -q -p no:cacheprovider tests/unit/test_verification.py tests/lean/test_proof_audit.py`: **32 passed in 59.47s**. Strict mypy and Ruff passed. Independent reviewer previously reran indirect-dependency and theorem-type substitution negatives without finding an acceptance bypass. The autonomous elementary certificate in `runs/elementary-search-smoke` passed all four audit checks. Mathlib revision is lock-derived; the current checkout matches, but this is not an attestation of every compiled dependency byte.
