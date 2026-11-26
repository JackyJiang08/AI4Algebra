import Mathlib.Data.ZMod.Basic
example : addOrderOf (1 : ZMod 3) = 3 := by
  simp only [addOrderOf_eq_iff, Nat.reduceLT]
  decide
