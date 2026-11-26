# 7-ddqn_retrieval-000

Outcome `budget_exhausted` (`steps`). Search produced no independently verified proof. See the stuck report for the observed goals.

Policy `ddqn_retrieval`, episode `run-24a87ebe1d627549-seed-7-ddqn_retrieval-000`. Lean `4.34.0-rc1`, Mathlib `de5ce8a9a66a4aa68a9bdbb35b63a06d34d9ca11`. Archived 2026-11-26T02:55:35.275500+00:00.

Original artifacts `runs/lean-improvements-cutoff/trials/7/ddqn_retrieval/000`. The run directory contains the frozen configuration and results.

Reproduce from the repository root using a fresh output directory:

```powershell
python -m ai4algebra evaluate --offline --dotenv runs/lean-improvements-offline.env --config configs/lean-elementary.json --training-run runs/lean-improvements-train --split validation --stop-on-closure --max-steps 1 --probes-per-node 1 --output runs/lean-improvements-cutoff-replay
```
