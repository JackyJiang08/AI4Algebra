# Verified source demonstration

Lean checked the reference solution for `composeLinearMap` on 2026-11-27T02:30:30.238872+00:00. The kernel reported no axioms for `AI4Algebra.Benchmarks.Gold.ExternalSubgroups.composeLinearMap`. Lean 4.34.0-rc1, Mathlib `de5ce8a9a66a4aa68a9bdbb35b63a06d34d9ca11`.

Run `subgroups-references-20261126`, attempt `reference-001`. The checked declaration is in `AI4Algebra/Benchmarks/Gold/ExternalSubgroups.lean`. Replay this copy from the project root:

```powershell
lake env lean records/succeeded/subgroups-references-20261126/composeLinearMap/reference-001/proof.lean
```
