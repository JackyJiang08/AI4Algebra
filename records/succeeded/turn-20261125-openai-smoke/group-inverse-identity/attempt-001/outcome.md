# Verified live-provider group proof

Outcome: **verified** (`audit_accepted`). Task: `group-inverse-identity`, training split.
Run: `turn-20261125-openai-smoke`, attempt 001, 2026-11-25.

GPT-6.2 Astra, high reasoning, proposed a single typed `simp_only` step using
`mul_inv_cancel` and `mul_one`. Fresh Lean replay accepted the original theorem,
its type, permitted axioms and dependency closure. A separate offline CLI replay
also accepted the certificate; see `recheck-verdict.json`.

Application API usage: one generation request, one input-token preflight,
2,233 input tokens, 60 output tokens, zero cached tokens. The local price ledger
settled USD 0.020264, with USD 0 outstanding, against a USD 0.50 turn/run cap.
This is application usage accounting, not a provider billing invoice.

The original solve command exited 1 after archiving the accepted proof: its console
could not encode the inverse symbol on Windows. Thus `solve.json` was not written.
The proof and verdict are genuine pre-error artifacts; no summary was fabricated
to conceal that CLI failure. The reporting path was subsequently fixed and tested.

Original artifacts: `runs/turn-20261125-openai-smoke/` and its `result/` directory.
`run.json` records the actual code, environment and policy identities at execution.
The later reporting fix changes the source digest; this record is retained as the
original run rather than being relabeled as a run of the modified source.

Executed solve command:

```powershell
python -m ai4algebra solve --config configs/lean-live-smoke.json --dotenv .env --task group-inverse-identity --mode deterministic --probes-per-node 1 --stop-on-closure --run-id turn-20261125-openai-smoke --output runs/turn-20261125-openai-smoke
```

`--mode deterministic` selects the search ordering, not an offline tactic provider;
the run configuration enabled OpenAI and the trace records `provider_status: ok`.

Offline reproduction, using the archived certificate and an absent settings file:

```powershell
python -m ai4algebra verify --offline --dotenv records/absent.env --task group-inverse-identity --certificate records/succeeded/turn-20261125-openai-smoke/group-inverse-identity/attempt-001/certificate.json --output runs/live-proof-replay
```

Do not repeat the paid solve to reproduce a certificate. For a new authorized paid
turn, use one new run/ledger; for retries within a turn, keep the existing ledger.
