# Exercise 11 through retrieval and Double DQN

This experiment replaces the earlier structural-only attempt as the requested
full-system test. The original attempt remains in its historical records. The
target is the unchanged conjunction assigning additive orders to all twelve
standard representatives in `ZMod 12`.

## Procedure

1. Load the public Exercise 11 statement and its existing exclusions. Keep the
   solution manual, Gold proofs, direct order formulas, and recorded answers out
   of the search inputs.
2. Extract the actual types and full transitive dependency closures of
   `addOrderOf_eq_iff` and `Nat.zero_lt_succ` from the pinned Mathlib environment.
   Check the closures against forbidden declarations before admitting the index.
   These are general minimality and positivity lemmas, not the table of answers.
3. Retrieve eligible premises for each observed goal, generate bounded typed
   actions, and probe them with Lean. The optional computational templates add
   explicit bundled simplification and ordinary `decide`; no native decision
   axiom or arbitrary tactic string is accepted. Retrieved names are retained in
   each generation trace. `decide` uses a finite `synthInstance.maxSize` limit of
   4096 to support the full nested conjunction; existing wall-clock and kernel
   checks remain in force. Computational templates try decision before splitting
   finite goals. The default structural template ordering is unchanged.
4. Bootstrap on the separately authored statement
   `addOrderOf (1 : ZMod 3) = 3`. This initialization episode uses deterministic
   action selection with real premise retrieval and computational actions. It
   does not load a prewritten proof or the target's solution.
   Only bootstrap probing stops on the first closing candidate. Target probing
   retains eligible alternatives for Q-value comparison.
5. Independently replay the bootstrap proof, check its original type, allowed
   axioms, and actual dependencies. Only then collect its actual transitions and
   publish discounted returns with a causal availability time.
6. Perform 32 optimizer updates. The online network selects the maximizing
   successor action; the target network evaluates that selected action. Terminal
   samples do not bootstrap. Synchronize the target every two updates. Save and
   reload a checkpoint bound to the encoder, policy, source catalog and frozen
   return memory.
7. Run best-first search on the complete Exercise 11 statement with that frozen
   DDQN policy. Record raw Q-values, eligible candidates, retrieved return values,
   blended scores and selected actions. Return lookup uses only earlier bootstrap
   publications and excludes the current episode. When configured, API proposals
   use one shared durable ledger capped at USD 0.50 for the whole run.
   A retry supplied with `--budget-run` opens the existing ledger without creating
   or initializing a database; missing, empty or mismatched ledgers fail closed.
8. Count a target proof only after independent replay, original-type alignment,
   axiom checks and transitive dependency checks pass. Archive all outcomes.

The action and encoder versions were incremented because adding `decide` changes
the feature dimensions. Old checkpoints are rejected rather than silently reused.
The previous structural runner retains its original action templates unless the
new computational option is explicitly enabled.

## Interpretation

This is a development demonstration on the user-selected training family. The
small bootstrap was designed while developing support for the requested problem;
the target is not an untouched held-out benchmark. A successful run establishes
that the components operated together and Lean accepted the resulting proof. It
does not establish a DDQN advantage over other methods or broad generalization.
Return retrieval being enabled is distinct from obtaining matching neighbors;
actual decision-level hits must be reported from `decisions.json`.
Premise retrieval uses a reviewed two-premise index, not an unrestricted search
over the whole Mathlib library. API proposals can use only those reviewed names.

The bootstrap uses deterministic selection, followed by real Double DQN optimizer
updates and trained target inference. This run does not claim additional
DDQN-guided exploration episodes or an already mature algebra policy.

## Reproduce

```powershell
lake build ai4algebra-observer ai4algebra-verifier AI4Algebra.Verification.Replay
uv run python -m ai4algebra.selected_full --output runs/exercise11-new

# A same-turn retry shares the original logical paid run and all its charges.
uv run python -m ai4algebra.selected_full --output runs/exercise11-retry --budget-run runs/exercise11-new
```

The default reads the local provider configuration. `--offline` explicitly disables
model proposals and is a different run condition. Use a fresh run ID and respect
the shared per-turn paid budget; starting another directory does not authorize a
fresh paid allowance within the same turn.

Measured attempts: `runs/exercise11-full-20261125/`,
`runs/exercise11-full-20261125-retry/`, and `runs/exercise11-full-20261125-final/`.
All use the original logical paid ledger; no second allowance was created.
Development failures and
capability diagnostics are preserved under the corresponding
`records/failed/exercise11-full-development-20261125/` and
`records/reports/exercise11-full-development-20261125/` directories.

## Result

The first bootstrap exhausted its candidates after six actions and 49 probes
(656.53 seconds), before any model request. Its trace showed that a closing
`decide` probe was available but deterministic initialization selected a structural
split first. The computational-order correction addresses that observed failure.

The next bootstrap verified a two-action proof, produced two transitions and
completed 32 updates. Its target search was deliberately interrupted after a
separate capability check identified the decision-instance size limit. It spent
USD 0.1762 across six settled requests, with zero outstanding reservation. The
in-memory target trace was not flushed before interruption; no target action list
or verified proof is invented for that attempt. Its successful bootstrap and
checkpoint remain archived independently of the interrupted target.

**The final full-system search verified Exercise 11.** The accepted proof covers
all twelve representatives, with orders
`[1, 12, 6, 4, 3, 12, 2, 12, 3, 4, 6, 12]` for `0, 1, ..., 11` respectively.

| Measurement | Actual final result |
|---|---|
| Bootstrap | Verified; two actions, seven probes, two collected transitions |
| Double DQN training | 32 optimizer updates, 16 target synchronizations |
| Published returns | Two, from the earlier verified bootstrap only |
| Target policy | Frozen `ddqn_retrieval` checkpoint |
| Target search | Two expanded nodes, 15 probes, six Q-scored selections |
| Eligible choices at those decisions | 4, 3, 2, 1, 3, 2 |
| Return-memory matches | Zero across six decisions; no return-blending effect |
| Accepted proof path | Two actions; other selections explored discarded branches |
| Target elapsed time | 257.48 seconds |
| Independent audit | Replay, original type, axioms and all 3,477 dependencies passed |
| Final-attempt API work | Two generation requests and two token-count requests; proposal statuses `ok` |
| Final-attempt cost | USD 0.046736 |
| Whole-turn ledger | Eight settled generation requests; USD 0.222936 settled, USD 0 outstanding |

Both accepted actions were OpenAI proposals selected by the trained policy:
explicit simplification with `addOrderOf_eq_iff` and `Nat.zero_lt_succ`, followed
by bounded ordinary `decide`. The first action replaces the order claims with
their defining positive-exponent/minimality conditions; the second checks the
resulting finite arithmetic. No stored solution or direct order formula was used.

- [Accepted standalone Lean proof](../records/succeeded/exercise11-full-20261125-final/exercise-11/ddqn-retrieval/evidence/proof.lean)
- [Independent verification verdict](../records/succeeded/exercise11-full-20261125-final/exercise-11/ddqn-retrieval/evidence/verdict.json)
- [Full search trace](../records/succeeded/exercise11-full-20261125-final/exercise-11/ddqn-retrieval/evidence/search.json)
- [Summary and accounting](../records/reports/exercise11-full-20261125-final/summary.json)
- [Q decisions and return lookups](../records/reports/exercise11-full-20261125-final/decisions.json)
- [Frozen checkpoint](../records/reports/exercise11-full-20261125-final/checkpoint.json) and [optimizer updates](../records/reports/exercise11-full-20261125-final/updates.json)
- [Exact input snapshots](../records/reports/exercise11-full-20261125-final/input-snapshots.json) and [shared ledger export](../records/reports/exercise11-full-20261125-final/api-ledger.json)

Independent review restored the checkpoint and memory, recomputed all six Q
decisions exactly, reconciled the accepted proof/archive bytes, and checked the
single ledger. Validation passed: 391 non-Lean tests; both final real-Lean action
and replay tests (bootstrap and complete target); strict mypy and Ruff across 95
Python files. The earlier audit/applicability suite also passed. The precise scope
is recorded in [validation.json](../records/reports/exercise11-full-20261125-final/validation.json);
this is not a claim that all 25 existing Lean tests were rerun.

The other nine selected exercises have not yet received this full-system evaluation.
