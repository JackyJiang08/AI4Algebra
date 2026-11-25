# formalization: executable tasks

Status: elementary and pinned Stacks curation/ingestion validated; autonomous benchmark results are tracked in evaluation.
Requirements: [proposal](../proposal.md). Interfaces: [detailed design](../detailed-design.md).
Assignment and shared-file policy: [master plan](../../RETRIEVAL_DDQN_PLAN.md).

- Owner role: GPT-6.2 Sol High; escalate difficult mathematical/debugging issues to GPT-6.2 Astra High.
- Prerequisites: F02, C01/C02, Lean bridge compatibility spike L01.
- Exclusive edit scope: `src/ai4algebra/formalization/`, `AI4Algebra/Benchmarks/`, `data/formalizations/`, `tests/unit/test_formalization.py`, `tests/lean/test_statements.py`, `tests/lean/test_stacks_lean.py`. Coordinator integrates Lean root imports/build targets.
- Focused validation: `uv run pytest -q tests/unit/test_formalization.py tests/lean/test_statements.py`.
- Also run Ruff and mypy on the owned code/tests. Full gates are in [progress](progress.md).

Each checkbox is one independently reviewable change. Add the executed command, result,
and artifact path under the item when completing it. Mocks cannot satisfy a real-Lean gate.

- [x] **FM01 — Represent curated statement mappings and explicit faithfulness evidence.** Acceptance: Include source, assumptions, quantifiers, Lean type/import hash, mapping status and evidence provenance.

- [x] **FM02 — Create elementary Lean statements in modules separate from gold proofs.** Acceptance: All designated statements elaborate under the pinned toolchain; search cannot import solution modules.

- [x] **FM03 — Build protected reference proofs for elementary fixtures.** Acceptance: Fresh verification establishes task solvability; proofs are not available in search environments/prompts.

- [x] **FM04 — Record target constants, known equivalent aliases and dependency families.** Acceptance: Negative fixtures reject disguised target aliases and circular statement dependencies.

- [x] **FM05 — Map feasible Stacks tags to curated Lean statements after G3.** Acceptance: Document mathematical convention differences, extra assumptions and unresolved mappings; no automatic semantic-certification claim.

- [x] **FM06 — Validate mapping status transitions and benchmark admission.** Acceptance: Unresolved/mismatched statements excluded with reasons; compile success alone cannot upgrade faithfulness to gold.

## Handoff

Return changed files, contract changes (if any), exact test commands/results, artifact paths,
known limitations and unresolved blockers. Do not edit another owner's files or mark other
modules complete. The coordinator integrates shared config changes and updates progress.


## Accepted elementary evidence (2026-11-25)

Main reproduced `python -m pytest -q tests/unit/test_corpus.py tests/unit/test_formalization.py tests/lean/test_statements.py`: **35 passed in 12.55s**. Strict mypy and Ruff passed for both modules and their tests. The real Lean batch checks all four original types and protected/typed proofs, excludes known answer aliases, and validates mapping evidence separately from typechecking. Source and mapping reads reject protected source/build paths before opening, including tested Windows junction aliases. Stacks tasks remain open.

## Accepted pinned Stacks evidence

Pinned official commit `a04446e57ec1fbc252a871afcec7752fb2807b14`; selection report `data/manifests/stacks-selection.json`: 9 tags reviewed, 6 excluded, 3 curated tasks across disjoint families (2 full statements, 1 explicitly labeled subclaim). Exact upstream license/notice are under `data/manifests/sources`. Immutable Git-object ingestion, cross-file references, scope omission rejection and credential-free Git environment tests passed.

Worker final configured corpus/formalization/Stacks unit + real Lean suite: **43 passed in 69.94s**, no skips. Independent review reproduced the upstream snapshot and native 00GJ audit with 4,912 complete transitive dependencies. Main full configured pytest subsequently passed **348 tests in 406.75s**, no skips, including all Stacks tests. This validates curated statements and test-only certificates, not autonomous Stacks search or learned performance. B06 remains the separate training/evaluation gate.
