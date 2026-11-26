# Selected group theory benchmark

The ten [user-selected questions](../data/training_questions.md) now have explicit
Lean statements. The [user-provided solution manual](../AI4Algebra/Benchmarks/Gold/selected_group_solutions.md)
is stored with protected reference proofs. All exercises are selected for future
training; these measurements are not held-out generalization results or DDQN training.

## What is tested

**Reference verification:** protected Lean proofs establish that each complete
formalized statement is provable. A separate Lean invocation checks the public JSON
type against its reference theorem and rejects any transitive axiom outside
`propext`, `Classical.choice`, and `Quot.sound`. No `sorry` or `admit` is accepted.
This checks the reference formalization, not whether the search program can discover
the proof. Reference proofs may use established Mathlib results and tactics.

**Autonomous baseline:** the existing search engine attempts each public statement
without reading the manual or protected proofs. This is a deliberately limited
structural-tactic baseline: introductions, constructors, local exact proofs,
assumptions and reflexivity. It does not use a premise index, a trained DDQN policy,
or an OpenAI proposer. The `basic_premises` lists are prospective metadata and are
not used in this run. A successful search still requires fresh independent Lean
replay, original-type checking, axiom checking and the dependency audit.

The fixed limits are four physical applicability probes, depth four, four nodes,
eight candidates per generation, 60 seconds per step and 120 seconds per task.
Failed search and exhausted limits do not establish that a theorem is false.
Initial observation failures are reported separately from search failures.

## Formalization choices

- Exercise 11 checks all twelve additive orders in `ZMod 12`.
- Exercises 16, 23 and 22 use `orderOf`; Lean represents infinite order as zero.
  Exercise 22 retains both the conjugation statement and the `ab`/`ba` consequence.
- Exercise 15 uses the product of an arbitrary list, preserving noncommutative
  order and including the empty-product case.
- Exercises 26 and 27 construct a `Subgroup` whose carrier is exactly the specified
  set, so the operation is inherited from the original group.
- Exercise 25 concludes commutativity for every pair of elements.
- Exercise 9 constructs an additive subgroup of the real numbers and a subgroup
  of the real units. Real units correspond to nonzero real numbers, so the second
  carrier is precisely the requested nonzero set with inherited multiplication.
- Exercise 31 uses the finite group cardinality and requires a witness of exact
  order two. Its reference proof follows inverse pairing rather than importing
  Cauchy's theorem.

Public cases are in [group_cases.json](../data/selected/group_cases.json) and
[quadratic_cases.json](../data/selected/quadratic_cases.json). The only new public
Lean definition is the raw rational-coefficient set for Exercise 9. The reference
modules are not imported by the runtime and must never become training examples
or retrieval-memory entries without a separately reviewed training-data policy.

## Reproduce

```powershell
# Full reference type and axiom check; no model API.
uv run pytest -q tests/lean/test_selected_references.py

# Fixed structural-only search baseline; no .env or model API access.
uv run python -m ai4algebra.selected_benchmark --output runs/selected-groups-new --records records
```

Use a fresh output/run ID for each experiment. `--task exercise-16` selects a single
case for diagnosis; subset runs do not count as complete ten-exercise evaluations.
The runner rejects arbitrary external case-file paths and archives results after
each exercise. Runtime inputs, source hashes, limits, attempted steps and diagnostics
are preserved with the report.

## Records

- Reference successes: `records/succeeded/selected-reference-20261125/`.
- Failed reference-development drafts: `records/failed/selected-reference-development-20261125/`.
- Autonomous attempts: `records/succeeded/selected-groups-20261125/` or
  `records/failed/selected-groups-20261125/`, according to the verified outcome.

Reference-development failures are recorded as such, separately from autonomous
search failures. Original draft sources and compiler diagnostics are preserved.
The reference success archives explicitly identify their protected imports and
must not be counted as autonomous discoveries.

## Results: 2026-11-25

**Reference verification: 10/10 passed. Autonomous structural baseline: 0/10 proved.**
Nine initial goals were observed; Exercise 27 timed out during initial extraction.
Of the remaining nine, four exhausted their candidate frontier, four reached the
four-probe limit, and Exercise 9 hit a step timeout. These are bounded smoke results,
not scores for premise retrieval, a trained policy, or an LLM-assisted prover.

| Exercise | Reference proof | Structural-only attempt |
|---|---|---|
| 11 | Verified | [Probe limit reached](../records/failed/selected-groups-20261125/exercise-11/attempt-001/outcome.md) |
| 16 | Verified | [Probe limit reached](../records/failed/selected-groups-20261125/exercise-16/attempt-001/outcome.md) |
| 15 | Verified | [Candidate frontier exhausted](../records/failed/selected-groups-20261125/exercise-15/attempt-001/outcome.md) |
| 26 | Verified | [Candidate frontier exhausted](../records/failed/selected-groups-20261125/exercise-26/attempt-001/outcome.md) |
| 27 | Verified | [Initial goal extraction timed out (60 s)](../records/failed/selected-groups-20261125/exercise-27/attempt-001/outcome.md) |
| 25 | Verified | [Probe limit reached](../records/failed/selected-groups-20261125/exercise-25/attempt-001/outcome.md) |
| 9 | Verified | [Tactic/step timed out](../records/failed/selected-groups-20261125/exercise-9/attempt-001/outcome.md) |
| 23 | Verified | [Candidate frontier exhausted](../records/failed/selected-groups-20261125/exercise-23/attempt-001/outcome.md) |
| 22 | Verified | [Probe limit reached](../records/failed/selected-groups-20261125/exercise-22/attempt-001/outcome.md) |
| 31 | Verified | [Candidate frontier exhausted](../records/failed/selected-groups-20261125/exercise-31/attempt-001/outcome.md) |

The [complete original report](../records/reports/selected-groups-20261125/summary.json)
and [exact public input/runner snapshots](../records/reports/selected-groups-20261125/input-snapshots.json)
are preserved. All ten attempts used zero API requests and USD 0. The question and
case-file hashes matched the frozen run throughout the completed measurement.

An interruption-only reporting correction was made after this run: when no search
trace returns, the initial observation is now unknown rather than presumed failed.
It does not change any completed case above. The original implementation snapshot
is retained so its source identity is not relabeled as the corrected runner.

A separate [Exercise 27 diagnostic retry](../records/reports/selected-groups-20261125-ex27-retry/summary.json)
used 120 seconds per step and 180 seconds per task, with the same statement and
four-probe limit. It observed the initial goal and exhausted its two available
probes in 32.57 seconds without selecting an action or proving the theorem.
The [retry record](../records/failed/selected-groups-20261125-ex27-retry/exercise-27/attempt-001/outcome.md)
is retained alongside the original timeout; it does not replace the baseline row.
It also used zero API requests, zero settled charges and zero outstanding reservations.

Validation: 380 non-Lean tests passed; the new real-Lean integration test passed
and checked all ten reference types and axiom closures. Strict mypy, Ruff lint and
Ruff formatting passed across 91 Python files. Independent review reconciled the
statements, source hashes, traces and archives for both runs. The other 22 existing
Lean tests were not rerun for this extension.

## Next implementation work

Admit these tasks to the training corpus only after building reviewed mappings,
premise signatures and dependency exclusions. Extend the action set and search
support for list induction, explicit existential witnesses and subgroup structures,
arithmetic/order reasoning, auxiliary lemmas, and finite counting. Freeze these
choices before making stronger benchmark comparisons. A verified reference alone
does not supply a usable training trajectory for the current action policy.
