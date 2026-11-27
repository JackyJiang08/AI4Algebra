import Mathlib.GroupTheory.Sylow
import Mathlib.Algebra.Module.LinearMap.Defs
import Mathlib.Tactic

namespace AI4Algebra.Benchmarks.Gold.ExternalSubgroups

open Subgroup MonoidHom
open scoped Classical

lemma eq_bot_iff_card {G : Type*} [Group G] {H : Subgroup G} :
    H = ⊥ ↔ Nat.card H = 1 := by
  suffices (∀ x ∈ H, x = 1) ↔ ∃ x ∈ H, ∀ a ∈ H, a = x by
    simpa [eq_bot_iff_forall, Nat.card_eq_one_iff_exists]
  constructor
  · intro h
    use 1, H.one_mem
  · rintro ⟨y, -, hy'⟩ x hx
    calc x = y := hy' x hx
    _      = 1 := (hy' 1 H.one_mem).symm

lemma inf_bot_of_coprime {G : Type*} [Group G] (H K : Subgroup G)
    (h : (Nat.card H).Coprime (Nat.card K)) : H ⊓ K = ⊥ := by
  have D₁ : Nat.card (H ⊓ K : Subgroup G) ∣ Nat.card H := card_dvd_of_le inf_le_left
  have D₂ : Nat.card (H ⊓ K : Subgroup G) ∣ Nat.card K := card_dvd_of_le inf_le_right
  exact eq_bot_iff_card.2 (Nat.eq_one_of_dvd_coprimes h D₁ D₂)

end AI4Algebra.Benchmarks.Gold.ExternalSubgroups

#print axioms AI4Algebra.Benchmarks.Gold.ExternalSubgroups.inf_bot_of_coprime
