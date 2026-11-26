import AI4Algebra.Verification.Replay
import Mathlib.Data.ZMod.Basic

set_option autoImplicit false

theorem AI4Algebra.Benchmarks.SelectedAttempt.zmod3_warmup : (addOrderOf (1 : ZMod 3) = 3) := by
  ai4algebra_step "{\"operation\":\"simp_only\",\"goal_id\":\"g0\",\"lemma\":null,\"local_id\":null,\"arguments\":[],\"direction\":\"forward\",\"location\":null,\"simp_lemmas\":[\"Nat.zero_lt_succ\",\"addOrderOf_eq_iff\"]}"
  ai4algebra_step "{\"operation\":\"decide\",\"goal_id\":\"g0\",\"lemma\":null,\"local_id\":null,\"arguments\":[],\"direction\":\"forward\",\"location\":null,\"simp_lemmas\":[]}"
