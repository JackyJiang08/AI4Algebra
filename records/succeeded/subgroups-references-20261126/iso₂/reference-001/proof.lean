import Mathlib.GroupTheory.Sylow
import Mathlib.Algebra.Module.LinearMap.Defs
import Mathlib.Tactic

namespace AI4Algebra.Benchmarks.Gold.ExternalSubgroups

open Subgroup MonoidHom
open scoped Classical

lemma aux_card_eq {G : Type*} [Group G] {H K : Subgroup G} [Finite G] (h' : Nat.card G = Nat.card H * Nat.card K) :
    Nat.card (G ⧸ H) = Nat.card K := by
  have := calc
    Nat.card (G ⧸ H) * Nat.card H = Nat.card G := by rw [← H.index_eq_card, H.index_mul_card]
    _                             = Nat.card K * Nat.card H := by rw [h', mul_comm]

  exact Nat.eq_of_mul_eq_mul_right Nat.card_pos this

noncomputable def iso₂ {G : Type*} [Group G] {H K : Subgroup G} [H.Normal] [K.Normal] [Fintype G]
    (h : Disjoint H K) (h' : Nat.card G = Nat.card H * Nat.card K) : G ≃* (G ⧸ K) × (G ⧸ H) := by
  apply MulEquiv.ofBijective <| (QuotientGroup.mk' K).prod (QuotientGroup.mk' H)
  rw [Nat.bijective_iff_injective_and_card]
  constructor
  · rw [← ker_eq_bot_iff, ker_prod]
    simp [h.symm.eq_bot]
  · rw [Nat.card_prod]
    rw [aux_card_eq h', aux_card_eq (mul_comm (Nat.card H) _▸ h'), h']

end AI4Algebra.Benchmarks.Gold.ExternalSubgroups

#print axioms AI4Algebra.Benchmarks.Gold.ExternalSubgroups.iso₂
