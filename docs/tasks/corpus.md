# corpus: executable tasks

Status: elementary and pinned Stacks curation/ingestion validated; autonomous benchmark results are tracked in evaluation.
Requirements: [proposal](../proposal.md). Interfaces: [detailed design](../detailed-design.md).
Assignment and shared-file policy: [master plan](../../RETRIEVAL_DDQN_PLAN.md).

- Owner role: GPT-6.2 Sol Medium.
- Prerequisites: F02; Stacks portion after elementary milestone G3.
- Exclusive edit scope: `src/ai4algebra/corpus/`, `data/manifests/`, `tests/unit/test_corpus.py`, `tests/unit/test_stacks.py`, `tests/fixtures/corpus/`. Formalization owns Lean theorem statements.
- Focused validation: `uv run pytest -q tests/unit/test_corpus.py`.
- Also run Ruff and mypy on the owned code/tests. Full gates are in [progress](progress.md).

Each checkbox is one independently reviewable change. Add the executed command, result,
and artifact path under the item when completing it. Mocks cannot satisfy a real-Lean gate.

- [x] **C01 — Implement task manifest loading and source identity validation.** Acceptance: Reject duplicate IDs, missing statement hashes, invalid splits and unsupported schema versions.

- [x] **C02 — Inventory elementary group/ring fixtures with definitions and prerequisites.** Acceptance: Manifest names exact tasks, categories, proof-length expectations and beginner descriptions; include multi-goal/multi-step examples.

- [x] **C03 — Assign stable train/validation/test partitions by equivalence family.** Acceptance: Every task has one split; renamings and equivalent targets cannot cross splits; deterministic split hash saved.

- [x] **C04 — Implement pinned Stacks repository snapshot ingestion.** Acceptance: Record commit, source/tag hashes and attribution; no bulk HTML scraping, unstable API dependency or outbound contact.

- [x] **C05 — Resolve selected tags and extract statement/dependency metadata.** Acceptance: Tests cover section vs theorem tags, missing/moved entries, cross-file references and source mismatch.

- [x] **C06 — Separate raw proofs from search-visible statements and premises.** Acceptance: Gold proof fixtures are accessible to scorer/curation only; prove runtime payloads cannot contain them.

- [x] **C07 — Produce a pilot selection report after mapping feasibility checks.** Acceptance: Counts, exclusions and mathematical families reported; no claimed Lean equivalence solely from tag matching.

## Handoff

Return changed files, contract changes (if any), exact test commands/results, artifact paths,
known limitations and unresolved blockers. Do not edit another owner's files or mark other
modules complete. The coordinator integrates shared config changes and updates progress.


## Accepted elementary evidence (2026-11-25)

Main reproduced `python -m pytest -q tests/unit/test_corpus.py tests/unit/test_formalization.py tests/lean/test_statements.py`: **35 passed in 12.55s**. Strict mypy and Ruff passed for both modules and their tests. The real Lean batch checks all four original types and protected/typed proofs, excludes known answer aliases, and validates mapping evidence separately from typechecking. Source and mapping reads reject protected source/build paths before opening, including tested Windows junction aliases. Stacks tasks remain open.

## Accepted pinned Stacks evidence

Pinned official commit `a04446e57ec1fbc252a871afcec7752fb2807b14`; selection report `data/manifests/stacks-selection.json`: 9 tags reviewed, 6 excluded, 3 curated tasks across disjoint families (2 full statements, 1 explicitly labeled subclaim). Exact upstream license/notice are under `data/manifests/sources`. Immutable Git-object ingestion, cross-file references, scope omission rejection and credential-free Git environment tests passed.

Worker final configured corpus/formalization/Stacks unit + real Lean suite: **43 passed in 69.94s**, no skips. Independent review reproduced the upstream snapshot and native 00GJ audit with 4,912 complete transitive dependencies. Main full configured pytest subsequently passed **348 tests in 406.75s**, no skips, including all Stacks tests. This validates curated statements and test-only certificates, not autonomous Stacks search or learned performance. B06 remains the separate training/evaluation gate.
