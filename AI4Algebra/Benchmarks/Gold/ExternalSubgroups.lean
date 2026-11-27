-- Selected and adapted upstream reference solutions. See data/training/subgroups/.
import Mathlib.GroupTheory.Sylow
import Mathlib.Algebra.Module.LinearMap.Defs
import Mathlib.Tactic

namespace AI4Algebra.Benchmarks.Gold.ExternalSubgroups

open Subgroup MonoidHom
open scoped Classical

/-- Show that the image of a subgroup under a group homomorphism preserves subgroup inclusion. -/
theorem map_mono {G H : Type*} [Group G] [Group H] (φ : G →* H) (S T : Subgroup G) (hST : S ≤ T) : map φ S ≤ map φ T := by
  intro x hx
  rw [mem_map] at * -- Lean does not need this line
  rcases hx with ⟨y, hy, rfl⟩
  use y, hST hy

/-- Prove that mapping a subgroup successively along two group homomorphisms gives its image under their composite. -/
theorem map_comp {G H K : Type*} [Group G] [Group H] [Group K] (φ : G →* H) (ψ : H →* K) (S : Subgroup G) :
    map (ψ.comp φ) S = map ψ (S.map φ) := by
  ext x
  simp only [mem_map]
  constructor
  · rintro ⟨y, y_in, hy⟩
    exact ⟨φ y, ⟨y, y_in, rfl⟩, hy⟩
  · rintro ⟨y, ⟨z, z_in, hz⟩, hy⟩
    use z, z_in
    calc ψ.comp φ z = ψ (φ z) := rfl
    _               = ψ y := by congr
    _               = x := hy

/-- Construct the conjugate of H by x as a subgroup with carrier {x h x⁻¹ | h ∈ H}. Prove all three closure obligations. -/
def conjugate {G : Type*} [Group G] (x : G) (H : Subgroup G) : Subgroup G where
  carrier := {a : G | ∃ h, h ∈ H ∧ a = x * h * x⁻¹}
  one_mem' := by
    dsimp
    use 1
    constructor
    exact H.one_mem
    group
  inv_mem' := by
    dsimp
    rintro - ⟨h, h_in, rfl⟩
    use h⁻¹, H.inv_mem h_in
    group
  mul_mem' := by
    dsimp
    rintro - - ⟨h, h_in, rfl⟩ ⟨k, k_in, rfl⟩
    use h*k, H.mul_mem h_in k_in
    group

/-- Prove that conjugating H first by y and then by x equals conjugating it by x * y. -/
theorem conjugate_mul {G : Type*} [Group G] (x y : G) (H : Subgroup G) :
    conjugate (x * y) H = conjugate x (conjugate y H) := by
  ext z
  constructor
  · rintro ⟨h, h_in, rfl⟩
    use y*h*y⁻¹
    constructor
    · use h
    · group
  · rintro ⟨-, ⟨h, h_in, rfl⟩, rfl⟩
    use h, h_in
    group

/-- A subgroup is trivial if and only if its cardinality (Nat.card) is one. -/
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

/-- Prove that two subgroups with coprime cardinalities have trivial intersection. -/
lemma inf_bot_of_coprime {G : Type*} [Group G] (H K : Subgroup G)
    (h : (Nat.card H).Coprime (Nat.card K)) : H ⊓ K = ⊥ := by
  have D₁ : Nat.card (H ⊓ K : Subgroup G) ∣ Nat.card H := card_dvd_of_le inf_le_left
  have D₂ : Nat.card (H ⊓ K : Subgroup G) ∣ Nat.card K := card_dvd_of_le inf_le_right
  exact eq_bot_iff_card.2 (Nat.eq_one_of_dvd_coprimes h D₁ D₂)

/-- Given a finite group with |G| = |H| |K|, prove that the coset space G/H and the subgroup K have equal cardinality. -/
lemma aux_card_eq {G : Type*} [Group G] {H K : Subgroup G} [Finite G] (h' : Nat.card G = Nat.card H * Nat.card K) :
    Nat.card (G ⧸ H) = Nat.card K := by
  have := calc
    Nat.card (G ⧸ H) * Nat.card H = Nat.card G := by rw [← H.index_eq_card, H.index_mul_card]
    _                             = Nat.card K * Nat.card H := by rw [h', mul_comm]

  exact Nat.eq_of_mul_eq_mul_right Nat.card_pos this

/-- For disjoint normal subgroups H and K of a finite G with |G| = |H| |K|, construct the isomorphism K ≃ G/H using the quotient map restricted to K. -/
noncomputable def iso₁ {G : Type*} [Group G] {H K : Subgroup G} [H.Normal] [K.Normal] [Fintype G]
    (h : Disjoint H K) (h' : Nat.card G = Nat.card H * Nat.card K) : K ≃* G ⧸ H := by
  apply MulEquiv.ofBijective ((QuotientGroup.mk' H).domRestrict K)
  rw [Nat.bijective_iff_injective_and_card]
  constructor
  · rw [← ker_eq_bot_iff, (QuotientGroup.mk' H).ker_domRestrict K]
    simp [h]
  · symm
    exact aux_card_eq h'

/-- For disjoint normal subgroups H and K of a finite G with |G| = |H| |K|, construct G ≃ (G/K) × (G/H) using the pair of quotient maps. -/
noncomputable def iso₂ {G : Type*} [Group G] {H K : Subgroup G} [H.Normal] [K.Normal] [Fintype G]
    (h : Disjoint H K) (h' : Nat.card G = Nat.card H * Nat.card K) : G ≃* (G ⧸ K) × (G ⧸ H) := by
  apply MulEquiv.ofBijective <| (QuotientGroup.mk' K).prod (QuotientGroup.mk' H)
  rw [Nat.bijective_iff_injective_and_card]
  constructor
  · rw [← ker_eq_bot_iff, ker_prod]
    simp [h.symm.eq_bot]
  · rw [Nat.card_prod]
    rw [aux_card_eq h', aux_card_eq (mul_comm (Nat.card H) _▸ h'), h']

/-- Given only a function between groups and a proof that it preserves multiplication, derive preservation of identity and use it to prove preservation of inverses. -/
theorem map_inverse_from_mul {G H : Type*} [Group G] [Group H] (f : G → H)
    (hmul : ∀ x y, f (x * y) = f x * f y) (a : G) : f a⁻¹ = (f a)⁻¹ := by
  have hone : f 1 = 1 := by
    have h : f 1 * f 1 = f 1 * 1 := by
      rw [← hmul, one_mul, mul_one]
    exact mul_left_cancel h
  have h : f a * f a⁻¹ = 1 := by
    rw [← hmul, mul_inv_cancel, hone]
  exact eq_inv_of_mul_eq_one_right h

/-- Construct a linear map with underlying function g ∘ f and prove that it preserves addition and scalar multiplication. -/
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
