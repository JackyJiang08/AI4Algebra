import Mathlib.Algebra.Group.Defs
import Mathlib.Algebra.Ring.Defs

/- Author-reviewed Lean types for the original elementary exercises. -/

set_option autoImplicit false

namespace AI4Algebra.Benchmarks.Statements

universe u

def group_inverse_identity : Prop :=
  ∀ (G : Type u) [Group G] (a b : G), a * (b * b⁻¹) = a

def group_ordered_inverse : Prop :=
  ∀ (G : Type u) [Group G] (a b c : G), ((a * b) * (c * c⁻¹)) * b⁻¹ = a

def ring_distribute_sub : Prop :=
  ∀ (R : Type u) [Ring R] (a b c d : R), a * (b - c + d) = a * b - a * c + a * d

def ring_add_cancel_pair : Prop :=
  ∀ (R : Type u) [Ring R] (a b c d e f : R)
      (_ : a + b = a + c) (_ : d + e = f + e), b = c ∧ d = f

end AI4Algebra.Benchmarks.Statements
