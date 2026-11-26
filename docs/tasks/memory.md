# memory: executable tasks

Status: implemented; focused tests, static checks and independent review passed. End-to-end search integration is still pending.
Requirements: [proposal](../proposal.md). Interfaces: [detailed design](../detailed-design.md).
Assignment and shared-file policy: [master plan](../../RETRIEVAL_DDQN_PLAN.md).

- Owner role: GPT-6.2 Sol Medium.
- Prerequisites: F02, E; full publication integration after S/V.
- Exclusive edit scope: `src/ai4algebra/memory/`, `tests/unit/test_memory.py`.
- Focused validation: `uv run pytest -q tests/unit/test_memory.py`.
- Also run Ruff and mypy on the owned code/tests. Full gates are in [progress](progress.md).

Each checkbox is one independently reviewable change. Add the executed command, result,
and artifact path under the item when completing it. Mocks cannot satisfy a real-Lean gate.

- [x] **M01 — Implement bounded train-only proof transition replay.** Acceptance: Persist state/action semantics, next candidate set/mask, flags, status, run/task/branch IDs and split provenance.

- [x] **M02 — Sample without replacement and validate entire inserts before mutation.** Acceptance: Reject malformed and held-out transitions without partial FIFO eviction.

- [x] **M03 — Compute return records from eligible completed verified training branches.** Acceptance: No truncated episode, failed verification or unfinished branch published as solved experience.

- [x] **M04 — Query causal experience per compatible candidate identity.** Acceptance: Both transition_step and available_at strictly precede cutoff; exclude same episode and incompatible versions before ranking.

- [x] **M05 — Round-trip frozen memory with original availability metadata.** Acceptance: No relabeling availability on checkpoint load; reject split/source/mask/hash mismatches.

- [x] **M06 — Prove evaluation cannot mutate replay or return index.** Acceptance: Tests forbid insertion and assert byte-identical artifacts; record selection bias from success-only return memory.

## Handoff

Return changed files, contract changes (if any), exact test commands/results, artifact paths,
known limitations and unresolved blockers. Do not edit another owner's files or mark other
modules complete. The coordinator integrates shared config changes and updates progress.


## Accepted review evidence

Independent Sol High re-review confirmed the representation/memory fixes and passed focused tests, strict mypy and Ruff. Historical cutoff queries now reject unreconstructable history after eviction; publication retries preserve original timestamps; feature provenance and certificate identity are checked. Full search integration remains a later gate.

- [x] Export the reviewed training Lean solution bodies with source provenance.
  Manifest exports select validated training tasks. The selected development
  solutions have a separate opt-in archive. The exporter does not publish
  return memory or provide search inputs.
