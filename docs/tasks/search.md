# search: executable tasks

Status: implemented; independent review corrections verified. Live-provider validation is tracked separately as D05.
Requirements: [proposal](../proposal.md). Interfaces: [detailed design](../detailed-design.md).
Assignment and shared-file policy: [master plan](../../RETRIEVAL_DDQN_PLAN.md).

- Owner role: GPT-6.2 Sol High.
- Prerequisites: L, E, A; V before claiming any success; start with fake interfaces.
- Exclusive edit scope: `src/ai4algebra/search/`, `tests/unit/test_search.py`, `tests/lean/test_search_loop.py`.
- Focused validation: `uv run pytest -q tests/unit/test_search.py tests/lean/test_search_loop.py`.
- Also run Ruff and mypy on the owned code/tests. Full gates are in [progress](progress.md).

Each checkbox is one independently reviewable change. Add the executed command, result,
and artifact path under the item when completing it. Mocks cannot satisfy a real-Lean gate.

- [x] **S01 — Implement immutable proof-tree nodes and branch lineage.** Acceptance: Paths retain original statement and candidate identities; repeated states/loops have explicit handling.

- [x] **S02 — Implement deterministic and bounded best-first search baselines.** Acceptance: Stable tie breaking, resource accounting and candidate budgets; preserve parents with untried actions after productive children. A first legal but unsuccessful branch cannot hide a second proving edge; no learned model needed for smoke fixtures.

- [x] **S03 — Integrate candidate scoring, epsilon choice and Lean stepping.** Acceptance: Act only on the current candidate set; invalid tactics rollback; all remaining goals persist.

- [x] **S04 — Define explicit outcomes and provisional reward semantics.** Acceptance: Distinguish valid progress, invalid tactic, verified completion, generator/frontier exhaustion, search-budget truncation and infrastructure error; exhaustion is not a proven absorbing dead-end and lacks a bootstrapped sample unless a valid continuation is available.

- [x] **S05 — Call final verifier before returning success or terminal success reward.** Acceptance: Candidate closure is provisional; failed replay/axiom/dependency audit cannot create a positive training episode.

- [x] **S06 — Emit chronological per-branch transitions with real final observations.** Acceptance: Replay prefix work and branching do not fabricate sequential MDP transitions; bootstrap semantics match design.

- [x] **S07 — Run elementary end-to-end fixtures including a multi-step proof.** Acceptance: Artifacts include replayable script, audit certificate, attempted candidates and resource counts; expected failures stay failures.

## Handoff

Return changed files, contract changes (if any), exact test commands/results, artifact paths,
known limitations and unresolved blockers. Do not edit another owner's files or mark other
modules complete. The coordinator integrates shared config changes and updates progress.


## Accepted integration evidence (2026-11-25)

Main and the independent reviewer each reproduced the combined provider/candidates/search/bridge/verifier unit suite: **99 passed** (Main: 4.64s). The implementer reran both pinned real Lean search tests after all fixes: **2 passed in 48.97s**. Main separately ran the actual CLI on the validation ring identity and obtained a verified two-step proof in 35.59s, then re-audited its exported certificate with the separate verify command. Artifacts: `runs/elementary-ring-smoke/result` and `runs/elementary-ring-replay`.

Recovery worker requests count against the search cap, distinct advanced prefixes with equal exposed goals remain eligible, and cancellation interrupts concrete workers and suppresses late success rewards. Provider objects refuse credential serialization; slow connection cancellation cannot dispatch later; prompt premises omit unvalidated display text. All corresponding regressions passed independent review. No paid API calls were made.

- [x] Write `stuck.json` for an unsuccessful search. Preserve available goals,
  local hypotheses, path tactics, queued branches and cutoff reasons. The complete
  `search.json` records generation activity for explored branches.
