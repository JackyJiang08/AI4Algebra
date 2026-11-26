# 7-ddqn_retrieval-000

Outcome `verified` (`audit_accepted`). Independent Lean replay accepted the proof, theorem type, axioms and dependencies.

Policy `ddqn_retrieval`, episode `run-768cfc3b64cc1128-seed-7-ddqn_retrieval-000`. Lean `4.34.0-rc1`, Mathlib `de5ce8a9a66a4aa68a9bdbb35b63a06d34d9ca11`. Archived 2026-11-26T02:55:35.189670+00:00.

Original artifacts `runs/lean-improvements-validation/trials/7/ddqn_retrieval/000`. The run directory contains the frozen configuration and results.

Reproduce from the repository root using a fresh output directory:

```powershell
python -m ai4algebra evaluate --offline --dotenv runs/lean-improvements-offline.env --config configs/lean-elementary.json --training-run runs/lean-improvements-train --split validation --stop-on-closure --probes-per-node 2 --output runs/lean-improvements-validation-replay
```
