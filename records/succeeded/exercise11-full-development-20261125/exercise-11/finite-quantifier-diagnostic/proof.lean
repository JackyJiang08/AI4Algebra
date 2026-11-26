import Mathlib.Data.ZMod.Basic
set_option autoImplicit false
theorem diagnostic_target : addOrderOf (0 : ZMod 12) = 1 ∧ addOrderOf (1 : ZMod 12) = 12 ∧ addOrderOf (2 : ZMod 12) = 6 ∧ addOrderOf (3 : ZMod 12) = 4 ∧ addOrderOf (4 : ZMod 12) = 3 ∧ addOrderOf (5 : ZMod 12) = 12 ∧ addOrderOf (6 : ZMod 12) = 2 ∧ addOrderOf (7 : ZMod 12) = 12 ∧ addOrderOf (8 : ZMod 12) = 3 ∧ addOrderOf (9 : ZMod 12) = 4 ∧ addOrderOf (10 : ZMod 12) = 6 ∧ addOrderOf (11 : ZMod 12) = 12 := by
  simp only [(_root_.id (@addOrderOf_eq_iff)), (_root_.id (@Nat.zero_lt_succ)), (_root_.id (@Nat.forall_lt_iff_fin))]
  decide
#print axioms diagnostic_target
