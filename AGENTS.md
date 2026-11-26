# Persistent project instructions

These instructions apply to all future work in this repository.

## Paid application API budget

The user authorizes OpenAI tactic generation with a maximum of USD 0.50 per assistant
turn. This supersedes the older USD 1.00 limit and the earlier offline-only preference.
The limit covers application API requests, not Codex/development-agent billing.

Use at most one paid run and one durable budget ledger per assistant turn. Share it
across tasks, retries and workers, and reuse it on restart; never create another ledger
to obtain a fresh allowance in the same turn. Count settled charges plus outstanding
reservations against USD 0.50 and report both. If the ledger cannot support the next
request, continue offline or stop paid work. Keep keys exclusively in the ignored
local `.env`; never include them in records, logs, messages, commits or worker tasks.
Offline checks must use isolated settings and must not make live provider requests.

## Commits and pushes

The user authorizes committing and pushing important completed changes as part of
the normal workflow. Do this after each meaningful, validated milestone without
asking again for routine permission.

- Review the diff and run checks appropriate to the change before committing.
- Stage the files belonging to that milestone explicitly. Preserve unrelated user
  changes and do not commit credentials, `.env`, caches or temporary artifacts.
- Write a clear, brief commit message with an imperative subject describing the
  concrete change, for example `Add retrieval API benchmarks`. Add a short body
  only when the reason or validation needs explanation.
- Push the commit to the current branch's configured remote. Do not force-push or
  rewrite shared history. If a push fails, report the actual blocker.
- Briefly report what was committed, the commit hash, and whether the push succeeded.

## Full-system proof testing

For requested problem tests, use the complete proof-search pipeline: reviewed
premise retrieval, a compatible trained Double DQN policy, causal return retrieval,
and independent Lean replay/type/axiom/dependency verification. A deterministic
basic-tactic run is only an explicitly labeled ablation, never the requested result.
Record checkpoint identity, optimizer updates, Q-value decisions, retrieval activity
and all successful/failed attempts. Keep reference solutions out of search inputs.
Use external theorem/lemma APIs when useful; paid calls share the cap above. If a
required component is missing, implement it or report the blocker explicitly.

## Progress updates

While working, briefly summarize what you are currently doing. Give concise updates
at meaningful milestones and at least once per minute during sustained work. Include
the current activity, important findings or blockers, and the next step when useful.

## Problem and Lean records

Keep records of every successful and failed problem-solving attempt in the dedicated
`records/` folder, separate from application source and training data:

- `records/succeeded/<run-id>/<task-id>/<attempt-id>/`
- `records/failed/<run-id>/<task-id>/<attempt-id>/`

For each attempt, save the problem statement and source, its Lean statement, the
generated Lean proof or attempted Lean steps, and the outcome with available logs,
verification results and reproduction command. Follow `records/README.md`.

Only independently verified proofs belong under `succeeded`. Preserve unsuccessful
attempts, including timeouts and infrastructure failures, under `failed`, recording
the actual reason. A failed search does not mean the theorem is false. If no Lean
proof was generated, say so and retain the statement and available steps; do not
invent a proof or insert `sorry` to make the record appear complete.

Use a new attempt directory for retries. Preserve existing records and original run
artifacts. These archives may contain held-out answers: do not feed them into training,
premise retrieval, prompts or return memory, or weaken existing split restrictions.
