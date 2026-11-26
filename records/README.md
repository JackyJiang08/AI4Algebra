# Problem and Lean attempt records

This folder holds records of future successful and unsuccessful proof attempts,
as requested by the user. Persistent instructions are in [AGENTS.md](../AGENTS.md).
Existing historical artifacts remain in `runs/`; this change does not migrate them.

```text
records/
  succeeded/<run-id>/<task-id>/<attempt-id>/
  failed/<run-id>/<task-id>/<attempt-id>/
```

Each attempt directory should contain:

- `problem.md`: the mathematical problem, task ID, source/tag and original split.
- `statement.lean`: the original Lean statement with its imports and context. When
  no complete proof exists, preserve the declaration as commented source rather
  than adding an admitted proof.
- `proof.lean`: the generated proof, when available. For unsuccessful attempts,
  retain the actual partial source or tactic sequence as `attempt.lean` or
  `attempted-steps.json`, clearly labeled as incomplete/unverified.
- `outcome.md`: verified success or the actual failure status/reason, timestamp,
  run/attempt IDs, original artifact paths and reproduction command.
- Available verification certificates, verdicts, search traces and error logs.

Copy evidence from the original run; keep original artifacts intact. Include the
recorded Lean/Mathlib versions and configuration or links to their run metadata.
Do not include credentials. Do not overwrite earlier attempts or count incomplete
proofs as successes. These records are an archive, not an additional training corpus.

The first archived live-provider proof is under
`succeeded/turn-20261125-openai-smoke/group-inverse-identity/attempt-001/`.
Its outcome records both successful Lean verification and the console error that
followed it. Agents are responsible for archiving their attempts; an automatic
application-level archive exporter is not installed.

The [selected group benchmark](../docs/selected-group-benchmark.md) has three
distinct record sets: verified references in `succeeded/selected-reference-20261125/`,
reference-development errors in `failed/selected-reference-development-20261125/`,
and autonomous structural-search outcomes under the `selected-groups-20261125` run ID.
Reference successes deliberately import protected proofs and are never counted as
autonomous discoveries. The selected-exercise runner automatically archives its own
attempts; the general solve/train/evaluate commands still require agent-managed copies.
