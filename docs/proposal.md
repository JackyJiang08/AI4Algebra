# AI4Algebra requirements

Status: original requirements implemented offline; latest extension recorded 2026-11-25.
See progress for verified outcomes and the remaining limits of the small proof corpus.
Inputs: [user workflow](../prompt.md), [procedure diagram](../assets/mermaid-diagram.png),
[assignment plan](../RETRIEVAL_DDQN_PLAN.md), repository inspection, and user answers.

## 1. Goal and confirmed decisions

Build a Python application that searches for algebra proofs and uses Lean to check every
accepted proof. The initial audience does not need prior algebra knowledge: commands,
reports, examples, and error messages must explain their mathematical terms.

- **D1 confirmed:** elementary group and ring exercises first; Stacks Project afterward.
- **D3 confirmed:** curated Lean statements first; automatic translation later.
- **D2 updated:** paid tactic generation is authorized using OpenAI `gpt-6.2-astra`,
  reasoning effort `high`, with a maximum **USD 0.50 per assistant turn**. Use one
  durable run/ledger per turn, shared across tasks, workers and retries. Offline
  commands remain available without a key; development-agent billing is separate.
- **D4 extension:** configure Stacks Project, LeanExplore and Loogle retrieval APIs in
  `.env` and add reproducible, opt-in benchmarks. Current endpoints are keyless.
  Store results separately, measure availability/ranking independently of proof success,
  and preserve offline training and all proof eligibility boundaries. See the
  [benchmark specification](retrieval-api-benchmark.md).
- Development roles: GPT-6.2 Astra High for documentation and complex debugging;
  GPT-6.2 Astra Medium/Low for coordination; GPT-6.2 Sol High/Medium for coding/testing.
  These agent selections do not establish a runtime API model identifier.
- Python with uv is the requested project workflow. Preserve the existing NumPy baseline.
- Implement every missing block of the procedure diagram, including final proof replay.
- Prefer the Stacks Project for the later theorem corpus, with stable source attribution.
- Produce independent modules, pytest coverage, passing mypy and Ruff, and task checklists.
- Main Agent tracks progress and delegates implementation/testing to Sub-Agents.
- Once requirements are settled, development should proceed without routine human intervention.
- Keep API credentials in an ignored local `.env`; never insert actual keys into documentation.

## 2. Decision record

| ID | Question asked | Effect of the answer | Current state |
|---|---|---|---|
| D1 | Which algebra scope comes first? | Corpus and milestone ordering | Answered: elementary group and ring exercises, then Stacks |
| D2 | Which API provider/model ID, reasoning level and maximum USD per run for paid tactics? | Provider adapter, credentials, calls and cost limits | OpenAI gpt-6.2-astra, high reasoning, USD 0.50 maximum per assistant turn using one shared run/ledger; key stays in ignored local .env |
| D3 | Curated Lean statements first, or automatic informal-to-Lean translation in the first milestone? | Formalization module scope | Answered: curated statements first, automatic translation later |

All questions asked during requirements discovery are answered. The design's implementation
choices remain testable engineering decisions, not user claims about performance. If a new
product ambiguity emerges, ask rather than invent an answer. Routine technical choices are
delegated to agents. Offline/deterministic providers remain usable without keys. Do not ask
the user to paste credentials into the conversation.

The USD 0.50 cap covers all paid tactic-generation requests in one assistant turn.
Use at most one paid solve/train/evaluate run and one shared ledger per turn, across
every theorem, retry and worker. Restarts of the same run keep the same
ledger; budget exhaustion stops paid calls. It does not describe ChatGPT/Codex development
agent billing. Enforce conservative pre-call reservations and reconcile provider usage;
fail closed if pricing or maximum billable token bounds are unknown. No automatic budget
increase, provider substitution, paid tools or unaccounted pricing tier changes.

## 3. Baseline at requirements discovery

This section records the starting snapshot. See [progress](tasks/progress.md) for
implementation completed after the requirements were written.

- Existing `retrieval_ddqn/`: synthetic chain environment, Q-network, Double DQN, replay,
  return-memory retrieval, training/evaluation CLIs and evaluation checkpoints.
- Most recent validated baseline: 38 pytest cases; both CLI modes reproduce recorded
  metrics; `lake build` passes. See the [archived evidence](history/retrieval-ddqn-synthetic-baseline.md).
- Lean setup exists, pinned to `leanprover/lean4:v4.34.0-rc1`; mathlib revision is recorded
  in `lake-manifest.json`. `AI4Algebra.lean` imports only `AI4Algebra.Basic`.
  `AI4Algebra/Test.lean` is not part of that default import graph.
- No Python-to-Lean protocol, theorem corpus, formalization mapping, proof-state encoder,
  lemma matcher, proof search, proof verifier, or Lean benchmark exists yet.
- A `pyproject.toml` exists but no `uv.lock` was found; uv was not found on this shell's
  PATH. Mypy/Ruff are not configured. Assign setup and migration rather than claim it passed.
- `.env` and `.env.example` are placeholders only; no dotenv loader currently exists.

## 4. Scope and staged outcomes

### M0: foundations and executable contracts

Establish uv, typed boundaries, pytest/Ruff/mypy gates, secret handling, and a Lean protocol
compatibility test on the pinned toolchain. Existing synthetic behavior must remain covered.

### M1: elementary algebra proof loop

Use a small versioned set of group/ring exercises, each with explicit Lean hypotheses and
an expected statement. Include identity/inverse laws and distributivity-style examples,
plus multi-step examples exercising intermediate goals. These are fixture categories,
not claims of a finalized theorem list. Corpus tasks select and record exact statements.
Training, validation and test partitions must be distinct, with equivalence families grouped.

The application loads a task, observes all goals/hypotheses, builds legal candidates,
chooses a tactic, executes it, handles failure or remaining goals, and exports a completed
proof only after independent replay and axiom/dependency checks. Start with deterministic
and best-first baselines, then collect training traces and integrate candidate-aware DDQN.
A paid LLM adapter proposes candidates; Lean decides whether they are valid. A deterministic
provider remains available for baseline comparisons and offline tests.

### M2: Stacks-backed benchmark

Import a pinned source snapshot, resolve stable tags, map selected algebra statements to
Lean, and build dependency-aware held-out splits. Begin with a small feasible selection
from commutative algebra after M1, rather than assuming every Stacks result has a mathlib
equivalent. Track unsupported formalizations openly. Numeric corpus size and performance
goals are established in a benchmark manifest before runs, not invented after results.

### Deferred work

Broad algebraic geometry, arbitrary informal problem solving, MCTS, Sage/GAP certificates,
large semantic vector services, and general reusable strategy induction are later work.
They must not delay the elementary Lean loop. Automatic translation is deferred per D3.
A Stacks citation graph is not a semantic theorem hypergraph.

## 5. Functional requirements and responsible modules

| ID | Requirement | Module |
|---|---|---|
| R01 | Reproducible uv setup, configuration validation, redacted secrets and offline tests | foundation |
| R02 | Versioned exercises with source/provenance, imports, expected types and fixed splits | corpus |
| R03 | Preserve meaning of statements and distinguish mapped/validated/unresolved translations | formalization |
| R04 | Start theorem sessions, expose every goal and hypothesis, step/fork/close with bounded resources | lean-bridge |
| R05 | Encode proof state deterministically without gold-proof or split leakage | representation |
| R06 | Retrieve accessible lemma candidates, bind arguments, expose side goals, check applicability in Lean | candidates |
| R07 | Generate typed tactic candidates from deterministic templates and the selected paid LLM | candidates |
| R08 | Search bounded proof trees, select tactics, rollback failed branches, track actual final observations | search |
| R09 | Replay complete proofs against the original statement; check axioms and theorem dependencies | verification |
| R10 | Store training transitions and causally available verified episode returns | memory |
| R11 | Score variable candidate sets and update with masked Double DQN and a target network | learning |
| R12 | Frozen held-out evaluation, provenance audits, fair baselines and reproducible artifacts | evaluation |
| R13 | Beginner-readable CLI/reporting and automated unit, integration and quality gates | delivery |

## 6. Correctness and data isolation

1. A proof succeeds only when its original declared type is proved, replay passes, and the
   axiom/dependency policy passes. Empty goals alone are insufficient.
2. Do not accept `sorry`, `admit`, added axioms, changed hypotheses, target self-reference,
   or imported gold solutions as a proof. Report rejected cases distinctly from timeouts.
3. Separate statement-faithfulness evidence from proof verification. A typechecked
   translation is not automatically a faithful translation of English or Stacks TeX.
4. Train on train-only transitions. Freeze model, feature vocabulary, candidate policy,
   source index, and return memory during held-out evaluation.
5. Gold test proofs cannot enter prompts, candidate generation, retrieval, replay, training,
   or caches. Audit equivalent statements and transitive theorem dependencies, including
   library automation that might reveal a held-out answer.
6. Record source revisions, task and statement hashes, split manifests, seeds, configuration,
   toolchain and candidate-policy versions in every run artifact.
7. Proof-state observations are obtained from Lean. Search failures must not fabricate goals
   or manufacture successful transitions. Missing final observations exclude a transition
   from bootstrapped training and are reported as infrastructure failures.

## 7. Quality requirements

- Every module has pytest tests for its public contract, invalid inputs, and significant
  failure paths. Lean integration tests must run with real Lean in a required CI job.
- Mypy and Ruff cover new production code, the retained baseline, and tests; no blanket
  exclusions that hide untyped modules or failing checks. Annotate baseline code as needed.
- Default tests require no model credentials or network. Online provider tests are opt-in.
- The CLI reports unsupported statements, missing dependencies, malformed responses,
  timeouts and budget exhaustion clearly and saves diagnostic artifacts without secrets.
- Local Windows/PowerShell support is required by the current workspace. Verify the
  configured CI platform too; do not assume a Linux-only bridge works locally.
- Source acquisition uses cached, pinned snapshots. Repeated evaluation is offline.

## 8. Acceptance evidence

| Gate | Evidence required |
|---|---|
| G0 foundations | uv lock/sync from clean checkout; pytest, Ruff and mypy pass; existing 38-case baseline retained |
| G1 Lean bridge | Real Lean tests for valid, invalid, branching/multiple goals, completion, timeout, crash recovery and final observations |
| G2 trustworthy proof | Standalone proof artifact replays; exact statement identity, allowed axioms and dependency policy checked; negative fixtures rejected |
| G3 elementary loop | Fixed elementary train/validation/test manifest; deterministic solve/verify commands, run reports, train-split trace collection and saved multi-step proofs |
| G4 learning | Learned train/evaluate commands; candidate-masked DDQN numerical tests, causality tests, frozen evaluation and repeatable seeded workflows |
| G5 Stacks pilot | Source/tag-to-Lean provenance, statement evidence and dependency-aware splits; train on Stacks train split, select on validation, freeze and test on held-out split; report counts and checkpoint hashes |
| G6 delivery | Complete pytest suite, strict mypy, Ruff checks/format, Lean build, independent review, documented reproduction commands |

All designated software smoke fixtures must pass. Benchmark reports show numerator and
denominator, failed/unsupported tasks, effort, and uncertainty; there is no promised solve
rate or improvement over a baseline. Milestone completion requires its specified artifacts
and gates, not a flattering aggregate success percentage.

## 9. Beginner glossary

- **Group:** objects with a combination operation, identity and inverses.
- **Ring:** objects with addition and multiplication satisfying specified algebra laws.
- **Theorem / goal:** a statement to prove / a current obligation in that proof.
- **Hypothesis:** an assumption available for the current goal.
- **Lemma:** a previously proved fact that may help discharge a goal.
- **Tactic:** a command proposing a proof step to Lean.
- **Kernel:** the small checker that validates the resulting proof term.
- **Axiom:** an assumption built into or added to the logical environment.
- **DDQN:** a learning method estimating the usefulness of actions while separating
  next-action selection from evaluation by a target network.
- **Truncation:** stopping because a resource budget ends, rather than proving/failing a theorem conclusively.

## 10. Source references

Stacks is an advanced reference, so elementary fixtures precede its use here
([about](https://stacks.math.columbia.edu/about)). Its identifiers are stable
([tags](https://stacks.math.columbia.edu/tags)); the later selection can start from
[commutative algebra](https://stacks.math.columbia.edu/tag/00AO).
Prefer a pinned [public source repository](https://github.com/stacks/stacks-project)
and retain its [COPYING](https://github.com/stacks/stacks-project/blob/master/COPYING)
and attribution when storing source material. The [website API](https://stacks.math.columbia.edu/api)
is documented as unstable and asks prospective users to contact maintainers; it is not
a required runtime dependency, and no contact is authorized by this plan.

Engineering references: [uv project files](https://docs.astral.sh/uv/concepts/projects/layout/),
[Lean commands and axiom inspection](https://lean-lang.org/doc/reference/latest/Interacting-with-Lean/),
[Ruff](https://docs.astral.sh/ruff/), [mypy adoption](https://mypy.readthedocs.io/en/stable/existing_code.html).
Implementation must verify Lean APIs against the pinned local version, not blindly copy latest documentation.

Runtime provider reference: [GPT-6.2 Astra API model](https://developers.openai.com/api/docs/models/gpt-6.2-astra),
[reasoning settings](https://developers.openai.com/api/docs/guides/reasoning), and
[SDK/key setup](https://developers.openai.com/api/docs/libraries). Model identifier verified
2026-11-25; the implementation must pin its SDK and record the pricing schedule used for budgets.
