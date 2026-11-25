# AI4Algebra detailed design

The first release takes a curated elementary group or ring statement, searches for a proof one Lean tactic at a time, and outputs a replayable Lean theorem. A group has an operation, an identity and inverses. A ring also has addition and multiplication related by distributivity. A tactic acts on a goal, which is one outstanding obligation in a proof. A tactic can replace one goal with several.

This is an implementation design. The working Python package `retrieval_ddqn` runs a synthetic chain experiment. Its fixed left/right actions, one-hot states and checkpoints belong to that experiment. Proposed Python modules live under `src/ai4algebra/`. Use `lean_bridge` as the Python module name for **lean-bridge**. The pinned Lean project supplies the execution environment. Feature owners should build against the interfaces below using fixture implementations, then test the real adapters together. See the [requirements](proposal.md), [procedure diagram](../assets/mermaid-diagram.png) and [module task checklists](tasks/progress.md).

## Decisions and delivery order

| Decision | Effect on implementation |
|---|---|
| D1. Elementary exercises first, Stacks Project afterward | Deliver the elementary benchmark and proof loop before the Stacks importer and pilot. |
| D2. Offline training default | Use deterministic proposals without keys. The optional OpenAI provider retains `gpt-6.2-astra`/`high` and a hard USD 1.00 whole-run limit; it is disabled by default. |
| D4. Optional external retrieval benchmark | A separate `ai4algebra.api_benchmark` command loads only retrieval settings, measures bounded public requests, and writes reports outside proof training. No service results enter proof candidates automatically. See [benchmark specification](retrieval-api-benchmark.md). |
| D3. Curated Lean statements first | Store and review an explicit source-to-statement mapping. Automatic informal-to-Lean translation is later work. |
| Development roles | GPT-6.2 Astra high for documentation and complex debugging, Astra medium/low for coordination, Sol high/medium for coding and testing. Development role names do not configure the application API. |

The order is contracts and pin compatibility → curated elementary manifest → all-goal Lean execution and independent replay → deterministic and best-first search → verified training traces → candidate-aware DDQN → frozen comparisons → Stacks pilot. This lets the team diagnose a failing tactic or contaminated exercise before training a model on it.

## Boundary records and data flow

Use immutable, versioned values for public Python contracts, with strict JSON codecs at file/process boundaries. Signatures below describe the proposed interfaces. A name ending in `Id` denotes a typed identifier. `Digest` is a SHA-256 of specified, canonical UTF-8 data. Keep format, normalizer and environment versions in the digest input. Preserve order where it carries meaning, including hypotheses, goals and proof steps. Validate references, dimensions, finite numbers and enum values on decoding.

| Record | Required fields and meaning |
|---|---|
| `SourceRef` | Kind, stable source ID, pinned revision, relative location, content digest, attribution and license reference. |
| `Problem` | Task ID, source reference, learner-facing statement, family ID, split, approved imports, universe/binder context, immutable original Lean statement, statement digest, mapping evidence ID. Solution bodies have a separate storage/access boundary. |
| `Hypothesis`, `Goal` | State-scoped local ID, binder kind, displayed name/type, normalized expression and optional local definition value. Each goal carries its own ordered hypotheses, target and scoped goal ID. |
| `Snapshot`, `Observation` | Session/environment and prefix digests plus an opaque snapshot reference. Observation has an ordered tuple of every goal, the expression-format version and state digest. Search adds remaining depth and action availability to the decision input. |
| `LemmaRule` | Environment-qualified declaration, type digest, ordered typed binders, conclusion pattern, premises, typeclass obligations, allowed provenance and dependency-closure digest. |
| `Candidate`, `CandidateSet` | Candidate ID, structured operation, focused goal, permitted lemma/local references, typed arguments, direction/location, provenance and generator version. Set includes state digest, policy digest, ordered candidates, aligned eligibility mask and generation status. |
| `ProofNode`, `StepResult` | Parent/edge IDs, immutable snapshot, actual observation, branch depth and ordered candidate attempts. A step returns advanced, closed, rejected, or an infrastructure status with bounded diagnostics. Only committed child states get a new snapshot. |
| `Certificate`, `Verdict` | Original statement/environment digests, rendered proof and proof digest. Verdict contains separate replay, expected-type, axiom and declaration-dependency results plus tool versions, diagnostics, the overall status and a certificate_digest binding the full canonical certificate payload. Return publication rejects unbound or mismatched accepted verdicts. |
| `Transition` | Train episode/branch ID, task/split, monotone collection step, state and candidate set, chosen candidate ID, reward, actual successor observation and successor candidate set, terminated/truncated flags, outcome and feature/policy versions. Terminal successor candidate sets may be empty. |
| `ReturnRecord` | Immutable state/action features and candidate signature, discounted realized return, source transition step, publication step, split/episode, proof verdict reference and encoder version. |

Three relationships have different evidence and consumers. The **source graph** stores public citations between source IDs with pinned provenance. The **rule index** stores elaborated premise-to-conclusion records for permitted declarations. Lean matches these records against a goal's local context. The **proof tree** stores actions actually attempted from a particular task and the observations returned by Lean. A citation cannot establish applicability. An indexed rule cannot establish that a search branch succeeded.

## 1. Foundation · R01

**Interface.** `load_config(path, environ) -> RunConfig`, `load_manifest(path) -> RunManifest` and typed codecs for the records above. Define lightweight Python protocols at module boundaries and inject implementations through delivery. Keep file I/O, credentials, subprocesses, random generators and clocks out of mathematical record types.

Use uv to lock and sync dependencies declared in `pyproject.toml`. Add the proposed package alongside the retained one. Pin protocol version, encoder version, candidate policy, mathlib commit and Lean toolchain in each manifest. Store sanitized effective configuration, seeds, data/split hashes and code revision. Derive separate seeded streams for action selection, minibatch sampling and initialization. Write manifests and checkpoints by staging then atomically replacing the destination.

The proposed configuration loader explicitly reads ignored `.env` locally, with process environment overrides. Configure `AI4ALGEBRA_LLM_PROVIDER=openai`, `AI4ALGEBRA_LLM_MODEL=gpt-6.2-astra`, `AI4ALGEBRA_LLM_BASE_URL=https://api.openai.com/v1`, `AI4ALGEBRA_LLM_REASONING_EFFORT=high`, `AI4ALGEBRA_ALLOW_PAID_API=true`, and `AI4ALGEBRA_API_BUDGET_USD=1.00`. The sole credential is `OPENAI_API_KEY`. A blank key prevents paid requests. Tests inject an offline provider. There is currently no loader or application provider integration. Validate the configuration before a request. Keep secrets out of manifests, tracebacks and provider dumps.

Treat USD 1.00 as a hard cap across **all tasks, provider workers, retries and restarts of the same application run**. Accept a lower configured limit. Reject any higher effective limit. The cap applies to application requests for tactic proposals. Development-agent usage belongs to the development environment. Use decimal currency arithmetic and a run-scoped transactional ledger. Reserve the worst-case input and maximum output charge, including reasoning tokens, using a versioned, validated price schedule before each attempt. Conservatively account for all request content and billing tiers. Use a model-supported safe upper bound when exact token accounting is unavailable. Disable unaccounted service tiers, cache-write charges and billed tools. Settle reservations against actual reported usage and persist both reserved and actual amounts. On ambiguous delivery or billing, keep the reservation across process restarts. Reject a new request when its upper bound exceeds the remaining allowance or pricing cannot be bounded. The deterministic backend remains usable.

**Independent checks.** Strict config/codec round trips, unknown version, hash mismatch, invalid budget, two concurrent reservations against one ceiling, environment precedence and sentinel-secret redaction.

## 2. Corpus · R02

**Interface.** `Corpus.open(manifest) -> Corpus`, `problems(split) -> Iterable[Problem]`, `allowed_declarations(task_id) -> EligibilityPolicy`. The scorer has its own solution store. Give training, prompts, search and public manifests access to statements, evidence and permitted declarations only.

For the elementary release, curate identity/inverse and ring distributivity families plus multi-step and branching exercises. Preserve the complete original binder telescope and assumptions. Record the expected statement hash before search. Split by equivalence family, including renamed variables, symmetry variants and known restatements. Never promise a target solve rate from a small smoke fixture. Record unsupported/problematic items in the manifest and report counts.

Build an eligibility manifest per task/environment. Group alpha-renamings and known equivalent targets, including public mathlib aliases. Precompute transitive dependencies for declarations eligible as premises. Exclude the target, equivalent answer declarations, gold modules, and lemmas depending on a forbidden answer. Investigate suspected equivalent formulations using Lean checks and recorded mathematical review. Place unresolved collisions in a quarantine set. Syntactic hashing alone misses logically equivalent statements. A train-family answer cannot cross partitions through an alias, cache or imported theorem.

After the elementary gate, import a pinned checkout/archive of the public Stacks source. Store stable tag, commit, file locator, text hash, attribution/license and citation edges, then curate a small commutative-algebra pilot using the same contracts. A tag locates the mathematical item across site reorganization. The commit pins the actual text. Reconcile changed/removed records against prior snapshots. Repeated tests and evaluation read an offline cache. The documented website API is unstable and asks prospective consumers to contact the maintainers. The importer uses the public source archive. See [Stacks sources and references](proposal.md#10-source-references).

**Independent checks.** Small source fixtures with duplicate IDs, missing source records, changed content under a stable tag, grouped family splits, disguised answer aliases, transitive wrappers and missing mapping evidence.

## 3. Formalization · R03

**Interface.** `validate_mapping(problem, statement_checker) -> MappingEvidence`. Evidence records the source and Lean digests, a table mapping each mathematical object/hypothesis/conclusion to its binder/type, provenance of review, elaboration result and status (`curated_validated`, `needs_review`, `unsupported`). A new source, type or import digest invalidates earlier evidence.

Re-elaborate the curated statement in the pinned environment. Where a trusted reference formalization exists, compare the types in Lean under the same universes and assumptions, and record the outcome. Otherwise record the curated alignment and its review basis. A successful typecheck alone earns only elaboration evidence. Classify a missing hypothesis or changed quantifier as a mapping problem even if a proof of the changed statement compiles. Only validated mappings enter the scored proof benchmark. Preserve other items for coverage reporting. Apply the same procedure for Stacks TeX at the pilot stage.

**Independent checks.** A binder-renamed fixture should validate with unchanged meaning. A weakened target, reversed product in a general group, stale signature or unresolved source must fail the corresponding evidence check. Test meaning against the curated alignment. A concrete counterexample can expose a mistranslation.

## 4. Lean bridge · R04

**Interface.** `open(problem, limits) -> (Snapshot, Observation)`, `fork(snapshot) -> Snapshot`, `step(snapshot, candidate) -> StepResult`, `observe(snapshot) -> Observation`, `close(session) -> None`. Provide a fake bridge with the same result variants for unit tests. Own subprocess lifetime, cancellation and diagnostics here.

Run a **compatibility spike first** against `leanprover/lean4:v4.34.0-rc1` and the mathlib revision in `lake-manifest.json` (currently `de5ce8a9a66a4aa68a9bdbb35b63a06d34d9ca11`). Build a project-owned Lean observer that elaborates the original statement into a goal, executes typed tactics in a fresh proof context and exports the entire ordered goal/local state and closure status. Exercise it from Python and confirm the verifier can inspect the resulting declaration. Record the exact executable, pin and fixtures on Windows and CI. Any third-party REPL or incremental snapshot optimization needs parity on those tests.

The initial backend replays each prefix. A snapshot references the statement, flags/imports and ordered validated tactic prefix. Forking copies the reference. Stepping runs the prefix plus the new action in an isolated worker invocation. Check that replay of the parent reproduces its canonical observation. A rejected tactic leaves the parent intact. A sibling starts from the same parent. Prefix replay is slower than retaining a Lean process but makes rollback and restarts observable on this toolchain.

Use a UTF-8, versioned JSON subprocess protocol through a fixed executable and argument vector. Each request carries request/session IDs, operation, environment digest, snapshot and typed payload. A response echoes IDs and returns exactly one result or typed error. Route human diagnostics to stderr or a separately bounded field. Validate schemas, IDs, exit status, byte limits and deadlines. Terminate and reap the process tree on timeout, including Windows children. Reconstruct from the last valid prefix within the retry budget. Reject stale snapshot IDs, malformed/truncated frames, toolchain mismatches and divergent replay as infrastructure errors.

Use an ordered complete goal list. If a step focuses goal 1 and produces two side goals, both new obligations and the untouched siblings survive. Reject operations that shelve/admit goals. Check for unresolved metavariables and postponed obligations at closure. Display strings serve diagnostics. Typed expressions and scoped local references identify action operands. Partially elaborated observer sessions cannot produce certificates.

**Independent checks.** The real pinned worker must open, step, reject an invalid tactic, preserve siblings after split/focus, restore a parent, finish both sides of a branching goal, reject malformed output, cancel a slow process, recover after a crash and return the last actual observation at a search cutoff.

## 5. Representation · R05

**Interface.** `encode_state(observation, context) -> StateFeatures`, `encode_candidate(candidate, observation) -> ActionFeatures`. Freeze feature dimensions, code/vocabulary hash and scaling rules for each checkpoint. A lightweight starting encoder can hash normalized expression tokens into fixed-width vectors and add counts of goals, local types, side conditions and remaining depth. Action features include operation, eligible declaration signature, focus, direction and typed argument positions. Aggregate each goal with its local context in a documented order. Expose an overflow indicator if display/feature budgets clip data. The authoritative bridge state always retains all goals.

Normalize binder names and local IDs by structural position, preserve dependencies and binder order, include universes and environment ID in cache keys, and scope each action to its originating observation. Debug printing, task IDs, file paths, source tags, gold proofs, solution lengths and split labels stay outside model features. Stable seeded hashing makes reproduction independent of Python's randomized object hash. Treat a feature collision as a retrieval approximation. Correctness-sensitive pruning requires full-state equivalence evidence. Decline pruning if the observer cannot establish it.

**Independent checks.** Renamed binders, new side goal, two separately scoped locals with identical names, changed depth, unknown symbols, overflow and deterministic feature bytes across processes.

## 6. Candidates · R06–R07

**Interface.** `retrieve(observation, eligibility, k) -> tuple[LemmaRule, ...]`, `instantiate(rule, goal) -> tuple[Candidate, ...]`, `generate(snapshot, observation, limits) -> CandidateSet`. A `TacticProposer` takes a bounded view of the statement, current goals/hypotheses and eligible lemma signatures and returns structured suggestions. Implement deterministic and OpenAI Responses adapters behind this contract. Send the confirmed model ID and reasoning effort with a bounded output size. Validate the structured response against the same local action schema before any Lean execution. Every attempt, including SDK retries, must pass through the shared reservation ledger. Disable implicit retries when the adapter cannot account for them.

Index permitted rules by conclusion head and typed premises. Use inexpensive feature similarity to order matches. Instantiate pattern variables against the focused target and local hypotheses. Track explicit/implicit arguments and typeclass requirements. Test elaboration and applicability on a fork. Surface genuine residual premises as side goals. A syntactic match never forces success. Cache validated step outcomes by snapshot, candidate, environment and policy hashes so search can reuse a successful probe while charging all probes against the same work budget.

Start with a small typed action language such as local assumption, reflexivity, introduce, constructor, exact/apply an eligible lemma, directed rewrite and `simp only` with an explicit eligible list. Render from typed operands under the approved declaration policy. Model output enters through the same decoder, budget and checks. Reject free-form Lean commands, arbitrary tactic scripts, unrestricted global simplification/search, unknown names, invalid focus and synthesized imports. Instrument/audit actual elaborated dependencies as described in verification. Use bounded deterministic templates when a provider is unavailable, malformed or over budget. Record the reason and fallback counts.

Deduplicate by concrete structural candidate ID and deterministic order. Mask ineligible, failed-probe or previously attempted actions where appropriate. Persist all IDs, features, masks, provenance, generator status and cutoff policy used for a decision. A capped generator may miss a workable tactic. An empty legal batch triggers a bounded fallback or another frontier node and eventually a reported search limitation. Never treat an empty generated set as a mathematical dead end.

**Independent checks.** Known instantiation, wrong typeclass, unmatched side premise, inaccessible lemma, disguised unrestricted tactic, provider timeout/malformed output, duplicate ordering, budget cap, cache-policy mismatch and deterministic fallback.

## 7. Search · R08

**Interface.** `solve(problem, policy, bridge, generator, verifier, limits) -> SearchReport`. The report contains a tree trace, budget ledger, outcome, last observed state if available and the verified certificate on success. Policies consume the same state, candidate set and eligibility mask. Inject a stable priority queue, clock and deterministic RNG through test fixtures.

1. Open the original theorem and enqueue the root. Pop a frontier node, obtain all goals and eligible candidates, then choose an untried candidate under the named policy. For best-first search, use a documented, frozen ordering such as cumulative step cost then residual-goal heuristic and stable ID tie-break. Limit both node expansions and actual bridge/probe calls.
2. Step from the saved parent. Log rejected actions and retain the unmodified parent for other attempts. Enqueue a valid child with remaining goals. Check every goal while rendering the ordered proof path. Siblings never contribute proof steps or Bellman successors to one another.
3. On apparent closure, submit the complete branch to the independent verifier. Reward and publish a proof only after acceptance. A rejected artifact receives diagnostics and search may try a sibling. Keep verifier timeouts separate from logical rejections.
4. Stop when verified, frontier exhausted under the configured generator, or an explicit depth/node/probe/time limit is hit. Report `verified`, `candidate_exhausted`, `budget_exhausted`, `verification_rejected`, `unsupported` or `infrastructure_error` with a reason and counters. Record mixed branch outcomes in the trace.

After any attempted edge, keep or re-enqueue the parent when it has untried eligible actions,
including when the attempted edge produced a valid child. Mark attempted candidate IDs on
that parent to prevent repeating the same edge. Test a root whose first legal edge leads
to a branch that cannot be solved within the candidate policy, while its second edge proves
the task; the search must still discover the second edge within budget.

For initial online DDQN collection, use one linear behavior rollout per training episode. Best-first alternatives remain search traces. Only contiguous same-branch paths with well-defined action sets can supply learner transitions. A rejected step can be logged as an attempted edge. If used as a penalized decision, obtain the actual unchanged parent observation and its updated action mask. A reset or a jump to another open frontier node never substitutes for the successor. A simple proposed reward starts at +1 for verified closure and a small configurable negative cost per executed action. Record the reward version and constants before comparisons.

At a cutoff preserve the **actual final Lean observation** and final candidate set/mask suitable for a continuation. Learner `terminated` means an explicitly defined absorbing outcome such as verified success. A horizon or candidate-policy exhaustion is a truncation or an untrainable search diagnostic. At a limit, produce a continuation set under the pinned policy with a pre-reserved observation/candidate budget, recording the same decision-context convention used in training. If no valid successor or legal continuation is available, exclude that transition from bootstrapped replay and report its reason. Timed-out or lost sessions must be restored and observed before recording a state. Recovery failure yields a diagnostic. Verified closure at the limit has success precedence.

**Independent checks.** Stub-tree tests cover rollback, sibling ordering, deterministic ties, multi-goal paths, false closure, empty candidates, work charging, exhausted frontier and timeout with/without a final observation. Exercise a multi-step run on real Lean through delivery.

## 8. Verification · R09

**Interface.** `verify(problem, certificate, eligibility) -> Verdict`. Use a fresh process and a clean, pinned import environment. Rebuild the theorem header from the trusted corpus record, bind universes and hypotheses from that record, and insert only a rendered proof from validated operations. Reject mismatched source, statement, imports, policy or environment digests. Compile with the pinned checker and require a complete theorem with the intended name and full expected type. Compare elaborated types in the same universe context using Lean and record the exact header/hash. Check for unresolved obligations, failed diagnostics and unexpected declarations.

Inspect the theorem in Lean. Compute transitive axioms and require every reported axiom to be on an explicit, versioned benchmark allowlist validated on the fixture environment. Always reject `sorryAx`, `sorry`, `admit` and newly introduced axioms. The pinned mathlib helper `Mathlib/Util/AssertNoSorry.lean` demonstrates the `Lean.collectAxioms` call and detects `sorryAx`. Its single check covers only one forbidden axiom. Pin and test the wider allowlist and inspection implementation in the compatibility spike.

The initial proposed axiom allowlist is `propext`, `Classical.choice`, and `Quot.sound`,
subject to exact-name verification on the pinned toolchain. Any other axiom yields rejection,
not an automatic expansion of the allowlist. Reject native or external checking shortcuts
that introduce additional trusted assumptions. Record the complete observed axiom set even
when it is a subset of the allowlist.

Separately traverse declaration constants referenced by the elaborated proof/type and recursively by dependency bodies/types, using the pinned environment and cycle protection. Check direct and transitive references against the task's forbidden answer/alias set and permitted dependency policy, including references introduced by elaboration, instances or simplification. Record sufficient paths to explain rejections. Use trusted, audited environment summaries for imported declarations whose dependencies cannot be inspected directly. An unknown closure produces an indeterminate verdict. Reject target self-reference, shadowed targets, gold imports, an alias with the answer, and helper lemmas that rely on one. Restrict the tactic vocabulary in addition to this final audit.

Persist standalone Lean text, pin/import manifest, statement and proof digests, full axiom set, dependency audit and decision. An independent process must be able to repeat the verdict from the artifact. Only `accepted` can contribute to success metrics, positive terminal rewards and verified return memory.

**Independent checks.** Replay a valid proof. Reject changed assumptions, missing side goal, sorry/admit, a custom forbidden or transitive axiom, direct equivalent declaration, transitive wrapper and unauthorized simp lemma. Verify that a checker crash, missing import or incomplete dependency audit is reported distinctly.

## 9. Memory · R10

**Interface.** `Replay.add(transition)`, `Replay.sample(batch, rng)`, `ReturnMemory.publish(episode, verdict, available_at)`, `ReturnMemory.query(state, candidates, before_step, exclude_episode) -> scores`. Maintain replay for train-only valid steps separately from the index of realized proof returns. Store versioned candidate features/IDs and masks or immutable content-addressed references to them. Validate a batch before committing it to a bounded store.

Define a global monotone collection clock. Publish a verified, completed, non-truncated train trajectory atomically after its verdict arrives. Compute returns backward along its own branch. For step t, store both the collection step and the actual publication clock, including asynchronous verifier delay. A query admits only matching feature/policy versions, train provenance, a different episode, and both collection and publication strictly before the decision cutoff. Filter before nearest-neighbor ranking. Match only concrete eligible candidate signatures in the current state. Bound capacity and break ties deterministically. A miss leaves behavior scores unchanged. Validation/test runs read an immutable training snapshot at a fixed cutoff and cannot append.

No incomplete, truncated, verification-rejected, or unsupported episode enters verified return memory. Replay can contain a valid final truncation transition if its real next observation and usable candidates are present. Training data sampled from successful episodes is selective. Publish counts of accepted, omitted and failed episodes alongside learned results. Publish verified proof artifacts separately from memory. General strategy induction is later work.

**Independent checks.** Future record, delayed publication, same episode, held-out source, truncation with both flags, stale policy and failed verdict are excluded. Test atomic rejection, restore/cutoff round trips and a fixed nearest-neighbor example.

## 10. Learning · R11

**Interface.** `score(state_features, action_features) -> float`, `rank(state, candidate_set) -> ranked IDs`, `update(batch) -> UpdateMetrics`, `save/load(checkpoint)`. Use one small shared scalar network for every pair. For example, concatenate state and candidate features, apply a dense ReLU layer and a scalar output. Score ragged batches by flattening real candidate rows and tracking segment offsets, or pad and mask. Candidate position has no learned meaning.

For each sampled transition, evaluate the chosen state/candidate pair. For a verified terminal step the target is the observed reward. Otherwise select a legal successor candidate by the online network and use the target network to evaluate the same candidate.

```text
a* = argmax over stored eligible next candidates of Q_online(s_next, candidate)
y  = reward + gamma * Q_target(s_next, a*)
loss = mean((Q_online(s, chosen_candidate) - y)^2)
```

An eligible truncation uses this second equation. Tie-break by stable ID. Exclude nonterminal samples without an eligible successor or final observation and report counts. Keep targets detached. Initialize the target network from the online network and synchronize after a fixed number of optimizer updates. The behavior policy may blend matched verified returns with network scores using a configured weight, then explore among legal actions. Targets always use the two unblended networks. A missing memory match falls back to raw Q. Reuse typed NumPy numerical routines from the baseline only where these semantics hold.

Store model parameters, target parameters, update counter, encoder/policy versions, immutable memory snapshot/cutoff and run metadata in an evaluation checkpoint. Distinguish this format from a resumable training checkpoint, which would also need replay, RNG states, counters, configuration, pending episodes and reservations if implemented.

**Independent checks.** If legal online next scores are [1, 3] and target scores are [8, −2], then for reward 1 and gamma 0.5 the target is 0. Add an ineligible candidate scoring 100 and verify exact invariance. Check terminal reward-only, truncation bootstrap, reordered/ragged candidates, target sync cadence, selected-pair gradients, no target gradients, blend/fallback and deterministic restoration.

## 11. Evaluation · R12

**Interface.** `evaluate(manifest, checkpoint, policy, limits, seeds) -> EvaluationReport`. Fix elementary train/validation/test families, seeds, environment, accessibility policy, probe/expansion/time budgets and number of runs before comparisons. Tune against train/validation only. Materialize disjoint dataset views, immutable train-memory/checkpoint and a semantic index filtered for the evaluation task. The scorer alone may read reference proofs for post-run diagnostics. Evaluation must not update model, optimizer, replay, return memory, vocabulary, prompt examples or cross-task caches. Isolate per-run transient computations and discard them. Version and freeze any precomputed candidate/provider fixtures with their provenance and split. Report recorded and live-provider conditions separately.

Compare deterministic enumeration, best-first heuristics, candidate-aware DDQN and DDQN plus causal return retrieval under the same eligibility and resource policy. If comparing generated candidates, report the candidate-generation condition and cost separately. Count all probes, errors and verifier calls, including work done during generation. Report solved/assigned, solved/validated, unsupported, rejected, budget-exhausted and infrastructure failures. Include solve time, depth, attempts, calls/cost, training steps, retrieval hits, and per-family/seed results with denominators. Use intervals or show raw seed-level counts where the sample is too small for a useful estimate. Preserve distinction between statement coverage and verified proof rate.

**Independent checks.** Canary reference proof invisible to all inference routes, held-out family and public mathlib alias rejection, transitive dependency fixture, byte-identical frozen training artifacts before/after, no writes to caches shared across tasks, identical seeds for each comparison and transparent mixed-outcome denominators.

## 12. Delivery · R13

**Interface.** Proposed CLI verbs `solve`, `verify`, `train` and `evaluate` compose the protocols above. No such Lean-backed CLI currently exists. `solve` accepts a manifest and task, `verify` accepts the original task and exported certificate, `train` consumes a train manifest plus configuration, and `evaluate` consumes a frozen checkpoint and held-out manifest. Use versioned machine-readable JSON plus human-readable summaries explaining the current goal and its assumptions. Distinguish an unproved exercise from a checker failure or invalid input in status and diagnostics.

Write per-run manifests, redacted event records, search traces, verified Lean files, verdicts, checkpoints and measured reports under a run-specific output path. Include a replay invocation with every proof and enough pinned data to run it offline. Limit logs and strip provider secrets. Link reports to task and branch IDs for investigation.

**Independent checks.** CLI argument errors, missing toolchain, inaccessible manifest, rejected proof, unavailable paid provider, successful exported proof and repeatable offline evaluation. Run from a clean fixture project on Windows and the configured CI platform.

## Configurable starting points and release gates

Suggested **software-smoke** limits for initial implementation are depth 8, 32 node expansions, 16 generated candidates per node and 128 total Lean step/probe calls per task. Bound individual Lean workers and entire tasks with independently configurable wall deadlines, calibrated on the pinned workers and CI hardware. Reserve capacity for final observation and independent verification, and record which limit fired. Suggested DDQN unit fixtures use gamma 0.5 and target sync every 2 updates to make arithmetic inspectable. These are engineering starting points. Benchmark manifests must record their actual limits, seeds, discount, rewards, feature dimensions, eligibility, pricing policy and memory cutoff before results are collected.

| Gate | Required executable evidence |
|---|---|
| G0 · Foundation | Locked uv setup, baseline tests and both baseline CLI modes, typed record/config tests and quality checks covering all Python. |
| G1 · Lean bridge | Compatibility spike, real open/step/fork/rollback, multiple goals, crash/timeout recovery and validated final observations on the pinned versions. |
| G2 · Trustworthy proof | Fresh-process replay of the original statement, repeatable axiom/dependency audits and rejection of all negative certificate fixtures. |
| G3 · Elementary loop | Curated split/semantic evidence, deterministic solve/verify commands, multi-step best-first search, exported verified examples, train-split trace collection and distinct run/failure reports. |
| G4 · Learning | Learned train/evaluate commands, numerical masked-DDQN parity, causal verified memory, immutable evaluation and seeded ablations on grouped elementary splits. |
| G5 · Stacks pilot | Pinned tags/attribution and mapping evidence; dependency-aware train/validation/test manifests; reuse Q06 on Stacks train data, select on validation, then frozen held-out test; report training counts, checkpoint hashes and unsupported/held-out denominators. |
| G6 · Delivery | CLI replay and quality checks from clean install, full integration suite, Lean build and independent review with reproducible evidence. |

Planned repository-root quality commands are below. Configure tooling to cover the retained package, new code, tests and any Python helper scripts. The existing repository has no verified uv lock or strict-mypy/Ruff setup for this design. Implement and exercise those gates before recording success.

```console
uv sync --locked --group dev --extra test
lake build
uv run pytest -q
uv run mypy --strict src/ai4algebra retrieval_ddqn tests
uv run ruff check src/ai4algebra retrieval_ddqn tests
uv run ruff format --check src/ai4algebra retrieval_ddqn tests
uv run pytest -q tests/lean tests/integration
```

Run the actual pinned bridge/verifier tests in required CI in addition to the default Lean target. The current top-level Lean file imports only `AI4Algebra.Basic`. A green `lake build` alone would miss a new observer or verifier left outside the build graph.
