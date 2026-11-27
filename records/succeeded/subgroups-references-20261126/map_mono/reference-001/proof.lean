import Mathlib.GroupTheory.Sylow
import Mathlib.Algebra.Module.LinearMap.Defs
import Mathlib.Tactic

namespace AI4Algebra.Benchmarks.Gold.ExternalSubgroups

open Subgroup MonoidHom
open scoped Classical

theorem map_mono {G H : Type*} [Group G] [Group H] (φ : G →* H) (S T : Subgroup G) (hST : S ≤ T) : map φ S ≤ map φ T := by
  intro x hx
  rw [mem_map] at * -- Lean does not need this line
  rcases hx with ⟨y, hy, rfl⟩
  use y, hST hy

end AI4Algebra.Benchmarks.Gold.ExternalSubgroups

#print axioms AI4Algebra.Benchmarks.Gold.ExternalSubgroups.map_mono
