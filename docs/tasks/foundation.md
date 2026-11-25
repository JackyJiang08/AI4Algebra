# foundation: executable tasks

Status: F01?F07 implemented and checked; bridge pin diagnostics now covered by unit and real-process tests.
Requirements: [proposal](../proposal.md). Interfaces: [detailed design](../detailed-design.md).
Assignment and shared-file policy: [master plan](../../RETRIEVAL_DDQN_PLAN.md).

- Owner role: GPT-6.2 Sol Medium.
- Prerequisites: None; runtime provider fields are settled in proposal D2.
- Exclusive edit scope: `src/ai4algebra/config.py`, `src/ai4algebra/contracts.py`, `src/ai4algebra/__init__.py`, `tests/unit/test_config.py`, `tests/unit/test_contracts.py`. Coordinator owns `pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example` and shared CI files.
- Focused validation: `uv run pytest -q tests/unit/test_config.py tests/unit/test_contracts.py`.
- Also run Ruff and mypy on the owned code/tests. Full gates are in [progress](progress.md).

Each checkbox is one independently reviewable change. Add the executed command, result,
and artifact path under the item when completing it. Mocks cannot satisfy a real-Lean gate.

- [x] **F01 — Add uv development dependencies and lock the supported Python environment.** Acceptance: Coordinator applies worker patch to pyproject/uv.lock; a fresh `uv sync --locked --group dev --extra test` works.

- [x] **F02 — Define immutable task, state, candidate, outcome, transition and certificate schemas.** Acceptance: JSON round trips, malformed versions/fields, finite values, identities and split checks pass.

- [x] **F03 — Implement configuration loading with environment-over-.env-over-config precedence.** Acceptance: Missing/blank credentials fail only for live provider mode; secrets are redacted from errors and serialization.

- [x] **F04 — Validate positive time/step/candidate/token limits and per-run paid budget.** Acceptance: Zero budget never becomes unlimited; provider/model are explicit and secrets are never checkpoints.

- [x] **F05 — Configure Ruff and strict mypy for all owned Python and tests.** Acceptance: Coordinator integrates config; no global ignore_errors or package-wide exclusions for baseline.

- [x] **F06 — Type and format existing retrieval_ddqn code without changing behavior.** Acceptance: Lead serializes ownership of baseline files; 38 regression tests and recorded seeded CLI outcomes remain unchanged.

- [x] **F07 — Document/install uv and record exact Lean/mathlib versions.** Acceptance: Windows instructions and toolchain mismatch diagnostics tested; no silent RC upgrade.

## Handoff

Return changed files, contract changes (if any), exact test commands/results, artifact paths,
known limitations and unresolved blockers. Do not edit another owner's files or mark other
modules complete. The coordinator integrates shared config changes and updates progress.


## Evidence (2026-11-25)

Installed from uv.lock using copied files in a fresh environment outside OneDrive.
Independent fresh offline install imported both packages with the Lean tree present.
Lead full pytest: 127 passed (89 foundation, 38 baseline); strict mypy and Ruff lint/format
passed across 18 Python files. Baseline worker reproduced byte-identical seeded checkpoints
and metrics in runs/f06. Reviewer confirmed budget precision, qualified admission rejection,
Unicode lemma operands, relative-source paths and transition consistency fixes.
Python uses src/ai4algebra to avoid the Windows Lean-directory case collision.
F07 is partial: uv and pin versions documented; runtime toolchain mismatch checks remain.

F07 follow-up: default Lean build includes observer; 24 protocol tests pass, including pin mismatch diagnostics. Real pinned Mathlib open/reject/close and branching tests passed.
