# 0000

Outcome `verified` (`audit_accepted`). Independent Lean replay accepted the proof, theorem type, axioms and dependencies.

Policy `deterministic`, episode `run-954fdd9a231fe32a-episode-0000`. Lean `4.34.0-rc1`, Mathlib `de5ce8a9a66a4aa68a9bdbb35b63a06d34d9ca11`. Archived 2026-11-26T02:52:56.026819+00:00.

Original artifacts `runs/lean-improvements-train/episodes/0000`. The run directory contains the frozen configuration and results.

Reproduce from the repository root using a fresh output directory:

```powershell
python -m ai4algebra train --offline --dotenv runs/lean-improvements-offline.env --config configs/lean-elementary.json --task group-inverse-identity --seed 7 --warmup-episodes 1 --episodes 1 --batch-size 2 --updates-per-episode 2 --probes-per-node 2 --stop-on-closure --output runs/lean-improvements-train-replay
```
