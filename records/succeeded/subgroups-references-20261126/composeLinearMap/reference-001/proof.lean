import Mathlib.GroupTheory.Sylow
import Mathlib.Algebra.Module.LinearMap.Defs
import Mathlib.Tactic

namespace AI4Algebra.Benchmarks.Gold.ExternalSubgroups

open Subgroup MonoidHom
open scoped Classical

def composeLinearMap {R M N P : Type*} [Ring R]
    [AddCommGroup M] [AddCommGroup N] [AddCommGroup P]
    [Module R M] [Module R N] [Module R P] (f : M →ₗ[R] N) (g : N →ₗ[R] P) :
    M →ₗ[R] P where
  toFun := g ∘ f
  map_add' := by
    intro x y
    change g (f (x + y)) = g (f x) + g (f y)
    rw [f.map_add]
    exact g.map_add _ _
  map_smul' := by
    intro r x
    change g (f (r • x)) = r • g (f x)
    rw [f.map_smul]
    exact g.map_smul _ _

end AI4Algebra.Benchmarks.Gold.ExternalSubgroups

#print axioms AI4Algebra.Benchmarks.Gold.ExternalSubgroups.composeLinearMap
