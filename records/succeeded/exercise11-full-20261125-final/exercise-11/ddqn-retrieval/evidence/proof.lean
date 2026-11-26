import AI4Algebra.Verification.Replay
import Mathlib.Data.ZMod.Basic

set_option autoImplicit false

theorem AI4Algebra.Benchmarks.SelectedAttempt.exercise_11 : (addOrderOf (0 : ZMod 12) = 1 ∧ addOrderOf (1 : ZMod 12) = 12 ∧ addOrderOf (2 : ZMod 12) = 6 ∧ addOrderOf (3 : ZMod 12) = 4 ∧ addOrderOf (4 : ZMod 12) = 3 ∧ addOrderOf (5 : ZMod 12) = 12 ∧ addOrderOf (6 : ZMod 12) = 2 ∧ addOrderOf (7 : ZMod 12) = 12 ∧ addOrderOf (8 : ZMod 12) = 3 ∧ addOrderOf (9 : ZMod 12) = 4 ∧ addOrderOf (10 : ZMod 12) = 6 ∧ addOrderOf (11 : ZMod 12) = 12) := by
  ai4algebra_step "{\"operation\":\"simp_only\",\"goal_id\":\"g0\",\"lemma\":null,\"local_id\":null,\"arguments\":[],\"direction\":\"forward\",\"location\":null,\"simp_lemmas\":[\"addOrderOf_eq_iff\",\"Nat.zero_lt_succ\"]}"
  ai4algebra_step "{\"operation\":\"decide\",\"goal_id\":\"g0\",\"lemma\":null,\"local_id\":null,\"arguments\":[],\"direction\":\"forward\",\"location\":null,\"simp_lemmas\":[]}"
