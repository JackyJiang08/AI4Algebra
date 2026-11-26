import AI4Algebra.Verification.Replay
import Mathlib.Algebra.Group.Defs

set_option autoImplicit false

theorem AI4Algebra.Benchmarks.Tasks.group_inverse_identity.{u} (G : Type u) [Group G] (a b : G) : (a * (b * b⁻¹) = a) := by
  ai4algebra_step "{\"operation\":\"simp_only\",\"goal_id\":\"g0\",\"lemma\":null,\"local_id\":null,\"arguments\":[],\"direction\":\"forward\",\"location\":null,\"simp_lemmas\":[\"mul_inv_cancel\",\"mul_one\"]}"
