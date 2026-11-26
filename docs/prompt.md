# Starting prompt: implement the AI4Algebra Lean proof loop

You are the Main Agent responsible for executing this repository's
[task assignment plan](../RETRIEVAL_DDQN_PLAN.md).

Read [requirements](proposal.md), [detailed design](detailed-design.md),
[progress](tasks/progress.md), each assigned module task file, and any applicable AGENTS.md.
The root [prompt.md](../prompt.md) specifies this documentation/implementation workflow.
Do not start from the archived synthetic plan as though it described the new work.

Follow the persistent [project instructions](../AGENTS.md): briefly summarize current
work throughout execution, and archive every successful and failed problem attempt
with its Lean statement, proof or partial steps, and outcome in the dedicated
[records folder](../records/README.md).
Commit and push meaningful validated milestones with clear, brief commit messages,
as authorized in those project instructions.

## Confirmed user requirements

- Elementary group/ring exercises first, then a curated Stacks Project pilot.
- Curated Lean statements first; automatic translation is later work.
- Application tactic generation is now authorized with OpenAI gpt-6.2-astra/high
  and USD 0.50 maximum per assistant turn. Use one durable paid run/ledger per turn,
  shared across tasks, retries and workers; see AGENTS.md. The local `.env` enables
  the provider. Offline commands remain available and require no key.
- Next phase: expand proof variety and benchmark rigor. Implement optional Stacks
  Project, LeanExplore and Loogle retrieval benchmarks with settings in `.env`,
  following [the retrieval benchmark specification](retrieval-api-benchmark.md).
  Keep retrieval measurements separate from verified theorem-proving success.
- Development: Astra High for documentation/complex debugging; Astra Medium/Low
  for Main coordination; Sol High/Medium for module coding/testing.
- Independent pytest tests for every module; all Python passes strict mypy and Ruff.
- Autonomous development after settled requirements, with progress tracking and
  module Sub-Agents. Do not ask for routine implementation approvals.

## Start and delegate

1. Inspect current working changes. Preserve Papers/, source prompt, assets, and other user work.
   Read the latest progress rather than assuming all work is unstarted.
2. Establish current tool versions, module status, and which baseline tests actually pass.
   Keep synthetic retrieval_ddqn CLIs and tests runnable. Do not rerun uv init over this project.
3. Main owns all shared files listed in the plan. Publish contracts and reserve worker paths
   before dispatch. Complete the pinned-Lean compatibility spike before promising a backend.
4. Dispatch independent ready modules using gpt-6.2-sol high for bridge/verification/
   candidates/search/learning/evaluation and medium for bounded utilities. Documentation
   and hard-debugging assignments use gpt-6.2-astra high. Main coordination uses
   gpt-6.2-astra medium or low. If the requested model is unavailable, report the blocker;
   do not silently substitute another model.
5. With four available agent slots, run at most Main plus three workers. Adapt to the
   actual slot count. Each handoff includes task IDs, objective, interfaces, exact file
   ownership, dependencies, checks, completion conditions and return format.
6. Workers edit only reserved paths. They return shared-file patches for Main integration.
   Main inspects source/test diffs, reproduces focused tests, resolves contract conflicts
   and updates progress after accepting evidence. Commit and push meaningful validated
   milestones under the standing authorization in AGENTS.md; report each commit briefly.
7. Follow dependency waves and gates G0–G6. Implement deterministic real-Lean proof
   search and independent replay before collecting training traces and adding DDQN.
8. Use a read-only independent reviewer after integration. Reviewer was not the implementer
   of the reviewed change. Fix confirmed issues and repeat affected gates before closing tasks.

## Non-negotiable invariants

- Original theorem type, assumptions and allowed imports are immutable.
- Lean provides actual goals, local contexts and branch states. Preserve every subgoal.
- All candidate generation goes through typed, bounded actions; reject arbitrary commands.
- Empty goals are provisional until fresh replay, original-type check, axiom allowlist and
  forbidden theorem-dependency audit pass. Reject sorry/admit, extra axioms and imported answers.
- Known equivalent targets/aliases and their transitive dependents cannot solve held-out tasks.
  Filter before ranking and audit actual elaborated dependencies, including automation.
- Keep source citation graphs, semantic premise records and proof-tree states separate.
- Variable candidates need shared Q(state,candidate) scoring and stored next masks/features.
  Online chooses, target evaluates. Retrieval blends behavior only.
- Truncations need actual next observations and defined continuation candidates to bootstrap.
  Missing observations, arbitrary frontier jumps and candidate exhaustion are not fabricated terminals.
- Replay and return memory are training-only. Publish returns only for completed verified,
  non-truncated training branches with actual availability timestamps and strict causal cutoffs.
- Evaluation freezes networks, vocabulary, candidate policy and train memory. Isolate caches.
- Stacks data use pinned source/tag provenance and curated formalization evidence.
  Never equate a typechecked translation with proven source fidelity.
- Budget accounting is durable, conservative, shared and capped at USD 0.50; reserve before
  dispatch, include reasoning and retries, retain ambiguous charges, never reset per theorem.
  Missing/unknown pricing or credentials prevents paid requests.
- Optional paid proposals use only the local OPENAI_API_KEY through the existing loader.
  Public retrieval adapters do not read that key. Never print, commit, copy to workers,
  or serialize keys. Default tests use mocks and deterministic proposals.

## Required completion checks

After foundation setup, from repository root:

```powershell
uv sync --locked --group dev --extra test
lake build
uv run pytest -q
uv run mypy --strict src/ai4algebra retrieval_ddqn tests
uv run ruff check src/ai4algebra retrieval_ddqn tests
uv run ruff format --check src/ai4algebra retrieval_ddqn tests
uv run pytest -q tests/lean tests/integration
```

Cover any added helper scripts with the same static checks. Run real-Lean bridge and verifier
tests in required CI; a basic lake build alone is insufficient. Network/API tests are opt-in.
Paid tactic tests require credentials and the shared USD 0.50 turn/run ledger. Keyless retrieval
benchmarks use separate request/response limits and do not enable paid proposals.
Record an unavailable live check as blocked or skipped, never passed. Preserve existing
synthetic numerical/leakage tests.

Produce standalone proof files, verifier certificates, source/split/environment manifests,
sanitized configs, training/evaluation results, budget usage and reproducible commands.
Separate verified-proof rate, statement-mapping coverage and infrastructure failures.
No performance claims from a small synthetic or smoke benchmark.

## Stop, uncertainty and reporting

Resolve routine technical problems autonomously. Escalate hard debugging to Astra High.
If a genuinely new requirement ambiguity appears, ask the user and continue independent
work; do not invent intent or silently weaken a correctness/budget gate. External blockers
such as unavailable keys or model access must be recorded precisely without claiming completion.
Never raise the budget or change the model without a new user instruction.

At each accepted handoff update the module checklist and progress log with exact commands
and results. A written plan is not implemented functionality. Finish only when the scoped
tasks/gates pass; otherwise report completed items and the concrete remaining blockers.
