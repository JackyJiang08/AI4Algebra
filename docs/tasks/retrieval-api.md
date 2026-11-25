# Retrieval API benchmark extension

This extends the original 79-task milestone. It does not change its historical results.
Requirements and interpretation: [benchmark specification](../retrieval-api-benchmark.md).

- [x] API01: Verify official Stacks, LeanExplore and Loogle endpoints/authentication.
- [x] API02: Add ignored local `.env` settings and a safe `.env.example`; preserve
  credentials and make offline proof training the default.
- [x] API03: Declare nine reproducible lookup/search cases across the three services.
- [x] API04: Implement bounded adapters, validated configuration, opt-in CLI and reports.
- [x] API05: Test request encoding, schemas, errors, no-network defaults and summaries;
  run strict typing/lint checks and independent review.
- [x] API06: Run keyless LeanExplore/Loogle live smoke and record actual results;
  keep Stacks skipped until maintainer coordination is complete.

Acceptance evidence: 367 non-Lean tests passed (41 new API tests plus 326 existing),
22 real-Lean tests deselected because this extension does not change Lean execution.
Strict mypy and Ruff lint/format pass across 88 files. Both keyless Lean search services
returned nonempty results for 3/3 live requests; exact-name hit@5 was 0/3 each.
Stacks live validation remains unperformed, explicitly recorded as disabled.
Reports and limitations are linked from the benchmark specification.
Independent read-only review reproduced all 41 focused tests and static checks;
no blocking findings remain.

Future work remains a larger curated proof corpus and stronger frozen comparisons.
Remote retrieval success is not evidence that these future proof tasks are complete.
