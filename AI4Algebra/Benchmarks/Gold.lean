import Mathlib.Algebra.Group.Defs
import Mathlib.Algebra.Ring.Defs

/- Protected reference proofs. This module is not imported by the benchmark runtime. -/

set_option autoImplicit false
set_option warningAsError true

namespace AI4Algebra.Benchmarks.Gold

universe u

theorem group_inverse_identity (G : Type u) [Group G] (a b : G) :
    a * (b * b⁻¹) = a := by
  rw [mul_inv_cancel, mul_one]

theorem group_ordered_inverse (G : Type u) [Group G] (a b c : G) :
    ((a * b) * (c * c⁻¹)) * b⁻¹ = a := by
  rw [mul_inv_cancel, mul_one, mul_assoc, mul_inv_cancel, mul_one]

theorem ring_distribute_sub (R : Type u) [Ring R] (a b c d : R) :
    a * (b - c + d) = a * b - a * c + a * d := by
  rw [mul_add, mul_sub]

theorem ring_add_cancel_pair (R : Type u) [Ring R] (a b c d e f : R)
    (hab : a + b = a + c) (hde : d + e = f + e) : b = c ∧ d = f := by
  constructor
  · exact add_left_cancel hab
  · exact add_right_cancel hde

end AI4Algebra.Benchmarks.Gold
