# representation: executable tasks

Status: implemented; focused tests, static checks and independent review passed. End-to-end search integration is still pending.
Requirements: [proposal](../proposal.md). Interfaces: [detailed design](../detailed-design.md).
Assignment and shared-file policy: [master plan](../../RETRIEVAL_DDQN_PLAN.md).

- Owner role: GPT-6.2 Sol Medium.
- Prerequisites: F02; fake observations allow work in parallel with L.
- Exclusive edit scope: `src/ai4algebra/representation/`, `tests/unit/test_representation.py`.
- Focused validation: `uv run pytest -q tests/unit/test_representation.py`.
- Also run Ruff and mypy on the owned code/tests. Full gates are in [progress](progress.md).

Each checkbox is one independently reviewable change. Add the executed command, result,
and artifact path under the item when completing it. Mocks cannot satisfy a real-Lean gate.

- [x] **E01 — Canonicalize typed state observations while preserving binding structure.** Acceptance: Tests distinguish dependent hypotheses and alpha-renaming; text similarity is never proof equality.

- [x] **E02 — Encode goal count/types, hypotheses and remaining resource context.** Acceptance: Deterministic finite feature shapes; no gold proof, target answer, split label or future-return feature.

- [x] **E03 — Encode candidate template, lemma type, bindings and side goals.** Acceptance: Action representation varies with candidate meaning rather than transient position in a list.

- [x] **E04 — Version and freeze feature extraction/vocabulary.** Acceptance: Train-only fitted statistics; unknown eval terms handled deterministically; JSON checkpoint parity.

- [x] **E05 — Add state/candidate provenance hashes and collision checks.** Acceptance: Reject mismatched encoder versions; snapshot identity remains distinct from approximate retrieval similarity.

## Handoff

Return changed files, contract changes (if any), exact test commands/results, artifact paths,
known limitations and unresolved blockers. Do not edit another owner's files or mark other
modules complete. The coordinator integrates shared config changes and updates progress.


## Accepted review evidence

Independent Sol High re-review confirmed the representation/memory fixes and passed focused tests, strict mypy and Ruff. Historical cutoff queries now reject unreconstructable history after eviction; publication retries preserve original timestamps; feature provenance and certificate identity are checked. Full search integration remains a later gate.
