# Exercise 22: verified reference

Status: **verified_reference**, not an autonomous solver success.

The complete public statement was checked against `AI4Algebra.Benchmarks.Gold.Selected.exercise22` in a fresh Lean compilation. The proof's transitive axioms were restricted to propext, Classical.choice and Quot.sound. The test treats warnings as errors and contains no admitted proof.

`proof.lean` intentionally imports the protected reference, while `reference-source.lean` preserves its complete source module. The archived mapping and combined check log provide evidence for this statement.

Reproduce: `python -m pytest -q tests/lean/test_selected_references.py`. Paid API cost: USD 0.

See the separate `selected-groups-20261125` records for structural-only autonomous attempts; reference acceptance is not scored there.
