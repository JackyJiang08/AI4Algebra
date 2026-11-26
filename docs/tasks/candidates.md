# candidates: executable tasks

Status: implemented; independent review corrections verified. Live-provider validation is tracked separately as D05.
Requirements: [proposal](../proposal.md). Interfaces: [detailed design](../detailed-design.md).
Assignment and shared-file policy: [master plan](../../RETRIEVAL_DDQN_PLAN.md).

- Owner role: GPT-6.2 Sol High.
- Prerequisites: F02, L01/L03, C03, FM04; D2 is settled: OpenAI gpt-6.2-astra, high, USD 0.50/turn using one shared run.
- Exclusive edit scope: `src/ai4algebra/candidates/`, `tests/unit/test_candidates.py`, `tests/unit/test_provider.py`, `tests/lean/test_applicability.py`.
- Focused validation: `uv run pytest -q tests/unit/test_candidates.py tests/unit/test_provider.py tests/lean/test_applicability.py`.
- Also run Ruff and mypy on the owned code/tests. Full gates are in [progress](progress.md).

Each checkbox is one independently reviewable change. Add the executed command, result,
and artifact path under the item when completing it. Mocks cannot satisfy a real-Lean gate.

- [x] **A01 — Build an accessible-premise index separate from experience memory.** Acceptance: Respect imports, allowed constants, split/equivalence exclusions and statement provenance before ranking.

- [x] **A02 — Retrieve typed lemma candidates and instantiate candidate arguments.** Acceptance: Type unification/applicability done through Lean; unmet premises become explicit side goals, not assumed facts.

- [x] **A03 — Implement a bounded typed tactic grammar and deterministic provider.** Acceptance: Support selected intro/exact/apply/rewrite/simp-only constructors; reject arbitrary command syntax and imported solutions.

- [x] **A04 — Implement the OpenAI Responses provider adapter behind one typed protocol.** Acceptance: gpt-6.2-astra with high reasoning; OPENAI_API_KEY loaded locally; mock response/error tests require no keys.

- [x] **A05 — Enforce request/token/cost limits, redaction, bounded retries and cancellation.** Acceptance: Reserve worst-case cost including reasoning before dispatch; retain uncertain charges after timeout; reconcile usage; one USD 0.50 ledger across every theorem/retry/worker; no hidden paid fallback or budget increase.

- [x] **A06 — Validate, deduplicate and deterministically order provider candidates.** Acceptance: Stable IDs bind semantic meaning and generator version; provenance is recorded separately; malformed output or unknown lemmas never bypass the typed grammar.

- [x] **A07 — Probe candidates in disposable Lean branches and preserve parent state.** Acceptance: Probe failure distinguished from proof success; count probes in effort metrics and avoid hidden state changes.

- [x] **A08 — Test target/alias/automation leakage and prompt visibility.** Acceptance: Prompt fixtures contain only allowed statements/premises; no test proofs, target equivalents or unfiltered global simp database.

## Handoff

Return changed files, contract changes (if any), exact test commands/results, artifact paths,
known limitations and unresolved blockers. Do not edit another owner's files or mark other
modules complete. The coordinator integrates shared config changes and updates progress.


## Provider review corrections (2026-11-25)

Independent review confirmed the official short-context Astra pricing, free input-token count endpoint and explicit no-write cache settings. Main fixed provider credential serialization and post-timeout dispatch during delayed connection setup; independent recheck passed all 12 provider tests. Main also removed unvalidated premise display strings from model payloads; only filtered structural type expressions are sent. The combined provider/candidate suite passed **17 tests**, with strict mypy and Ruff passing on the five changed files. Search cancellation and same-goal branch retention corrections are still in progress. No live requests have been made.

## Accepted integration evidence (2026-11-25)

Main and the independent reviewer each reproduced the combined provider/candidates/search/bridge/verifier unit suite: **99 passed** (Main: 4.64s). The implementer reran both pinned real Lean search tests after all fixes: **2 passed in 48.97s**. Main separately ran the actual CLI on the validation ring identity and obtained a verified two-step proof in 35.59s, then re-audited its exported certificate with the separate verify command. Artifacts: `runs/elementary-ring-smoke/result` and `runs/elementary-ring-replay`.

Recovery worker requests count against the search cap, distinct advanced prefixes with equal exposed goals remain eligible, and cancellation interrupts concrete workers and suppresses late success rewards. Provider objects refuse credential serialization; slow connection cancellation cannot dispatch later; prompt premises omit unvalidated display text. All corresponding regressions passed independent review. No paid API calls were made.
