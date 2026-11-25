# evaluation: executable tasks

Status: implemented, independently reviewed and validated on source-frozen elementary and Stacks runs.
Requirements: [proposal](../proposal.md). Interfaces: [detailed design](../detailed-design.md).
Assignment and shared-file policy: [master plan](../../RETRIEVAL_DDQN_PLAN.md).

- Owner role: GPT-6.2 Sol High.
- Prerequisites: B01–B05 require elementary C01–C03/C06, FM01–FM04, V/S and Q for learned comparisons. B06 additionally requires Stacks C04/C05/C07 and FM05/FM06, then reruns Q06 on its train split.
- Exclusive edit scope: `src/ai4algebra/evaluation/`, `tests/unit/test_evaluation.py`, `tests/integration/test_lean_cli.py`.
- Focused validation: `uv run pytest -q tests/unit/test_evaluation.py tests/integration/test_lean_cli.py`.
- Also run Ruff and mypy on the owned code/tests. Full gates are in [progress](progress.md).

Each checkbox is one independently reviewable change. Add the executed command, result,
and artifact path under the item when completing it. Mocks cannot satisfy a real-Lean gate.

- [x] **B01 — Freeze benchmark manifests and all evaluation inputs.** Acceptance: Record split hash, imports, policy/encoder/checkpoint hashes and no test-proof exposure.

- [x] **B02 — Run identical evaluation budgets for deterministic and learned baselines.** Acceptance: Compare deterministic best-first, Q-only, Q+return retrieval; premise retrieval remains controlled separately.

- [x] **B03 — Report verified success counts, effort and uncertainty across seeds.** Acceptance: Include invalid tactics, timeouts, unsupported tasks, tokens/cost, all Lean calls including probes, and replay failures.

- [x] **B04 — Add cross-split leakage and immutable-evaluation integration tests.** Acceptance: Reject target aliases, gold-source prompts, future memory and changed candidate generator checkpoints.

- [x] **B05 — Evaluate elementary held-out tasks and archive proof certificates.** Acceptance: Report actual rates without an invented performance promise; do not select checkpoints on test results.

- [x] **B06 — Train and test the later Stacks pilot with separate faithfulness/proof outcomes.** Acceptance: Reuse Q06 to train on the pinned Stacks train split, select only on validation, freeze checkpoint and evaluate disjoint test; report training counts, checkpoint hashes, held-out denominators, unmapped tags and dependency-policy limitations. No trainable pilot means G5 remains unmet; no contamination-free claim for unknown model pretraining.

## Handoff

Return changed files, contract changes (if any), exact test commands/results, artifact paths,
known limitations and unresolved blockers. Do not edit another owner's files or mark other
modules complete. The coordinator integrates shared config changes and updates progress.


## Accepted elementary evaluation evidence

Final training inputs: `runs/elementary-release-{7,11}`; frozen evaluation outputs: `runs/elementary-release-validation/evaluation.json` and `runs/elementary-release-test/evaluation.json`. Validation and test each contain **one distinct theorem**, evaluated with two independently trained seeds and three policies. Each report has **6/6 verified trials**, and each seed/mode row is **1/1**, not six distinct theorems.

All modes used identical max-depth 8, max-nodes 32, max-candidates 8, max-steps 8, probes-per-node 2, step timeout 120s, task timeout 600s and stop-on-closure. Each validation trial used three probes, one open and one audit; each test trial used five probes, one open and one audit. Held-out return retrieval had zero hits, and the methods showed no success/effort advantage on these tiny splits. Across-seed statistics are descriptive, not inferential confidence or generalization claims.

Main independently loaded both current-source checkpoints, compared both evaluation plans against the current catalog/code and exact frozen training identities, and verified **24 proof/trace file hashes per split**. The run orchestration also confirmed all **34 frozen training files stayed byte-identical** through validation followed by test. Checkpoints/training budget were fixed before evaluation; no test-based checkpoint or parameter selection was performed. Paid API requests and costs were zero. Main reproduced 12 CLI/evaluation unit tests; independent reviews and final 348-test suite cover source/candidate mismatches, feature context substitution, cross-split filters, immutable evaluation, writer races, and causal memory.

## Accepted Stacks training and evaluation evidence

Current input `runs/stacks-pilot-experiment-7/training.json`: one autonomously verified **00E5 image-on-points subclaim** trajectory, three selected actions, five probes plus one open and one independent audit, 123.56s; three exact transitions/return entries, two DDQN optimizer updates, cutoff 4. This small run trains from the verified warmup trajectory and does not add a later exploratory rollout. Checkpoint hash `b133c828f5f1f272b974acea8b66b5b8d536ebf105b18b5ebebd1580fbd3c7e1`. This does not prove the complete 00E5 homeomorphism statement.

Frozen outputs: `runs/stacks-pilot-experiment-validation/evaluation.json` (full 00GJ) and `runs/stacks-pilot-experiment-test/evaluation.json` (full 05CI). Every mode recorded **0/1 verified**, with `budget_exhausted/probe_limit`, ten probes plus one open, zero audit attempts and zero retrieval hits. These are unsolved tasks, not rejected mathematical statements or verified results. All three modes used candidates16/steps10/probes2/depth8/nodes32, step120s/task600s, stop-on-closure and the same frozen seed-7 model. No test-driven tuning or checkpoint selection occurred; the checkpoint used a predeclared training budget and was evaluated on validation before test. One seed gives no across-seed variation estimate.

Main independently reloaded the Stacks checkpoint against the final code/catalog, matched both evaluation plans to its exact frozen identity, verified all six trace file hashes and checked that failed trials contain no selected certificate or verdict. The orchestration confirmed all 12 frozen training files byte-identical. API requests/costs were zero. Full-tag mapping coverage (2) and subclaim coverage (1) remain separate from autonomous proof success; six other reviewed tags are excluded with reasons. Unknown model-pretraining contamination is not claimed absent, and this offline run used no model API.
