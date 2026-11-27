import Mathlib.GroupTheory.Sylow
import Mathlib.Algebra.Module.LinearMap.Defs
import Mathlib.Tactic

namespace AI4Algebra.Benchmarks.Gold.ExternalSubgroups

open Subgroup MonoidHom
open scoped Classical

theorem map_inverse_from_mul {G H : Type*} [Group G] [Group H] (f : G → H)
    (hmul : ∀ x y, f (x * y) = f x * f y) (a : G) : f a⁻¹ = (f a)⁻¹ := by
  have hone : f 1 = 1 := by
    have h : f 1 * f 1 = f 1 * 1 := by
      rw [← hmul, one_mul, mul_one]
    exact mul_left_cancel h
  have h : f a * f a⁻¹ = 1 := by
    rw [← hmul, mul_inv_cancel, hone]
  exact eq_inv_of_mul_eq_one_right h

end AI4Algebra.Benchmarks.Gold.ExternalSubgroups

#print axioms AI4Algebra.Benchmarks.Gold.ExternalSubgroups.map_inverse_from_mul
