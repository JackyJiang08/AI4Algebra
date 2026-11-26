import AI4Algebra.Verification.Replay
import Mathlib.Data.ZMod.Basic

set_option autoImplicit false

theorem AI4Algebra.Benchmarks.SelectedAttempt.zmod3_warmup : (addOrderOf (1 : ZMod 3) = 3) := by
  ai4algebra_step "{\"operation\":\"simp_only\",\"goal_id\":\"g0\",\"lemma\":null,\"local_id\":null,\"arguments\":[],\"direction\":\"forward\",\"location\":null,\"simp_lemmas\":[\"addOrderOf_eq_iff\",\"Nat.zero_lt_succ\"]}"
  ai4algebra_step "{\"operation\":\"decide\",\"goal_id\":\"g0\",\"lemma\":null,\"local_id\":null,\"arguments\":[],\"direction\":\"forward\",\"location\":null,\"simp_lemmas\":[]}"

run_cmd do
  let env ← Lean.getEnv
  let names := env.checked.get.constants.foldStage2 (fun a n _ => a.push n.toString) (#[] : Array String)
  Lean.logInfo (Lean.toJson names).compress
