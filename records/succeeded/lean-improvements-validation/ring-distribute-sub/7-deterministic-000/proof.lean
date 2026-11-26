import AI4Algebra.Verification.Replay
import Mathlib.Algebra.Ring.Defs

set_option autoImplicit false

theorem AI4Algebra.Benchmarks.Tasks.ring_distribute_sub.{u} (R : Type u) [Ring R] (a b c d : R) : (a * (b - c + d) = a * b - a * c + a * d) := by
  ai4algebra_step "{\"operation\":\"simp_only\",\"goal_id\":\"g0\",\"lemma\":null,\"local_id\":null,\"arguments\":[],\"direction\":\"forward\",\"location\":null,\"simp_lemmas\":[\"mul_add\"]}"
  ai4algebra_step "{\"operation\":\"simp_only\",\"goal_id\":\"g0\",\"lemma\":null,\"local_id\":null,\"arguments\":[],\"direction\":\"forward\",\"location\":null,\"simp_lemmas\":[\"mul_sub\"]}"
