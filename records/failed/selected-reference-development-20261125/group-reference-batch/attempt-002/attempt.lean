import Mathlib.Algebra.BigOperators.Group.List.Defs
import Mathlib.Algebra.Group.Subgroup.Defs
import Mathlib.Data.ZMod.Basic
import Mathlib.GroupTheory.OrderOfElement

/- Protected reference proofs for the selected exercises. Keep this module out of search imports. -/

set_option autoImplicit false
set_option warningAsError true

namespace AI4Algebra.Benchmarks.Gold.Selected

universe u

private theorem orderInZModTwelve (k n : ℕ) (h : 12 / Nat.gcd 12 k = n) :
    addOrderOf (k : ZMod 12) = n := by
  rw [ZMod.addOrderOf_coe k (by decide), h]

theorem exercise11 :
    addOrderOf (0 : ZMod 12) = 1 ∧
    addOrderOf (1 : ZMod 12) = 12 ∧
    addOrderOf (2 : ZMod 12) = 6 ∧
    addOrderOf (3 : ZMod 12) = 4 ∧
    addOrderOf (4 : ZMod 12) = 3 ∧
    addOrderOf (5 : ZMod 12) = 12 ∧
    addOrderOf (6 : ZMod 12) = 2 ∧
    addOrderOf (7 : ZMod 12) = 12 ∧
    addOrderOf (8 : ZMod 12) = 3 ∧
    addOrderOf (9 : ZMod 12) = 4 ∧
    addOrderOf (10 : ZMod 12) = 6 ∧
    addOrderOf (11 : ZMod 12) = 12 :=
  ⟨orderInZModTwelve 0 1 (by decide), orderInZModTwelve 1 12 (by decide),
    orderInZModTwelve 2 6 (by decide), orderInZModTwelve 3 4 (by decide),
    orderInZModTwelve 4 3 (by decide), orderInZModTwelve 5 12 (by decide),
    orderInZModTwelve 6 2 (by decide), orderInZModTwelve 7 12 (by decide),
    orderInZModTwelve 8 3 (by decide), orderInZModTwelve 9 4 (by decide),
    orderInZModTwelve 10 6 (by decide), orderInZModTwelve 11 12 (by decide)⟩

theorem exercise16 (G : Type u) [Group G] (x : G) :
    x ^ 2 = 1 ↔ orderOf x = 1 ∨ orderOf x = 2 :=
  orderOf_dvd_iff_pow_eq_one.symm.trans (Nat.dvd_prime Nat.prime_two)

theorem exercise15 (G : Type u) [Group G] (xs : List G) :
    xs.prod⁻¹ = (xs.reverse.map (fun x : G => x⁻¹)).prod := by
  induction xs with
  | nil => simp only [List.prod_nil, inv_one, List.reverse_nil, List.map_nil]
  | cons x xs ih =>
    simp only [List.prod_cons, mul_inv_rev, ih, List.reverse_cons, List.map_append,
      List.map_cons, List.map_nil, List.prod_append, List.prod_nil, mul_one]

theorem exercise26 (G : Type u) [Group G] (H : Set G) (hne : H.Nonempty)
    (hmul : ∀ a ∈ H, ∀ b ∈ H, a * b ∈ H) (hinv : ∀ a ∈ H, a⁻¹ ∈ H) :
    ∃ K : Subgroup G, (K : Set G) = H := by
  obtain ⟨a, ha⟩ := hne
  have hone : (1 : G) ∈ H := by
    simpa only [mul_inv_cancel] using hmul a ha a⁻¹ (hinv a ha)
  let K : Subgroup G := {
    carrier := H
    one_mem' := hone
    mul_mem' := fun {a b} ha hb => hmul a ha b hb
    inv_mem' := fun {a} ha => hinv a ha
  }
  exact ⟨K, rfl⟩

theorem exercise27 (G : Type u) [Group G] (x : G) :
    ∃ K : Subgroup G, (K : Set G) = {y : G | ∃ n : ℤ, x ^ n = y} := by
  let K : Subgroup G := {
    carrier := {y : G | ∃ n : ℤ, x ^ n = y}
    one_mem' := ⟨0, zpow_zero x⟩
    mul_mem' := by
      rintro a b ⟨m, rfl⟩ ⟨n, rfl⟩
      exact ⟨m + n, zpow_add x m n⟩
    inv_mem' := by
      rintro a ⟨n, rfl⟩
      exact ⟨-n, zpow_neg x n⟩
  }
  exact ⟨K, rfl⟩

theorem exercise25 (G : Type u) [Group G] (h : ∀ x : G, x ^ 2 = 1) :
    ∀ a b : G, a * b = b * a := by
  have inverse_eq (x : G) : x⁻¹ = x :=
    inv_eq_of_mul_eq_one_right (by simpa only [pow_two] using h x)
  intro a b
  rw [← inverse_eq (a * b), mul_inv_rev, inverse_eq b, inverse_eq a]

theorem exercise23 (G : Type u) [Group G] (x : G) (s t : ℕ) (hs : 0 < s) (ht : 0 < t)
    (horder : orderOf x = s * t) :
    orderOf (x ^ s) = t := by
  have hpow : (x ^ s) ^ t = 1 := by rw [← pow_mul, ← horder, pow_orderOf_eq_one]
  refine (orderOf_eq_iff ht).2 ⟨hpow, ?_⟩
  intro k hklt hk hkp
  rw [← pow_mul] at hkp
  have hdvd : s * t ∣ s * k := horder ▸ orderOf_dvd_of_pow_eq_one hkp
  have htdvd : t ∣ k := Nat.dvd_of_mul_dvd_mul_left hs hdvd
  exact (Nat.not_le_of_lt hklt) (Nat.le_of_dvd hk htdvd)

theorem exercise22 (G : Type u) [Group G] :
    (∀ x g : G, orderOf x = orderOf (g⁻¹ * x * g)) ∧
    (∀ a b : G, orderOf (a * b) = orderOf (b * a)) := by
  have preserve (x g : G) : orderOf x = orderOf (g⁻¹ * x * g) := by
    have h : SemiconjBy g⁻¹ x (g⁻¹ * x * g) := by
      simp only [SemiconjBy, mul_assoc, mul_inv_cancel, mul_one]
    exact h.orderOf_eq g⁻¹
  refine ⟨preserve, ?_⟩
  intro a b
  simpa only [mul_assoc, inv_mul_cancel_left] using preserve (a * b) a

private theorem even_card_of_involution {α : Type u} [DecidableEq α] (f : α → α)
    (hf : Function.Involutive f) (s : Finset α)
    (hmem : ∀ a ∈ s, f a ∈ s) (hfree : ∀ a ∈ s, f a ≠ a) : Even s.card := by
  induction s using Finset.strongInductionOn with
  | _ s ih =>
    by_cases hne : s.Nonempty
    · obtain ⟨a, ha⟩ := hne
      have hfa := hmem a ha
      have hfa' : f a ∈ s.erase a := Finset.mem_erase.mpr ⟨hfree a ha, hfa⟩
      let remaining := (s.erase a).erase (f a)
      have hsub : remaining ⊂ s :=
        (Finset.erase_ssubset hfa').trans (Finset.erase_ssubset ha)
      have hremaining : ∀ b ∈ remaining, f b ∈ remaining := by
        intro b hb
        obtain ⟨hbf, hba⟩ := Finset.mem_erase.mp hb
        obtain ⟨hneab, hb⟩ := Finset.mem_erase.mp hba
        refine Finset.mem_erase.mpr ⟨fun h => hneab (hf.injective h), ?_⟩
        refine Finset.mem_erase.mpr ⟨?_, hmem b hb⟩
        intro h
        exact hbf ((hf b).symm.trans (congrArg f h))
      obtain ⟨k, hk⟩ := ih remaining hsub hremaining
        (fun b hb => hfree b (Finset.mem_of_mem_erase (Finset.mem_of_mem_erase hb)))
      have hcard : remaining.card + 1 = (s.erase a).card := Finset.card_erase_add_one hfa'
      have hcard' := Finset.card_erase_add_one ha
      exact ⟨k + 1, by omega⟩
    · rw [Finset.not_nonempty_iff_eq_empty.mp hne, Finset.card_empty]
      exact ⟨0, rfl⟩

theorem exercise31 (G : Type u) [Group G] [Fintype G] (hEven : Even (Fintype.card G)) :
    ∃ a : G, orderOf a = 2 := by
  classical
  by_contra hnone
  let nonidentity := (Finset.univ : Finset G).erase 1
  have hclosed : ∀ a ∈ nonidentity, a⁻¹ ∈ nonidentity := by
    intro a ha
    refine Finset.mem_erase.mpr ⟨?_, Finset.mem_univ _⟩
    intro hone
    exact (Finset.mem_erase.mp ha).1 (by simpa only [inv_inv, inv_one] using congrArg Inv.inv hone)
  have hfree : ∀ a ∈ nonidentity, a⁻¹ ≠ a := by
    intro a ha hfix
    apply hnone
    have hsq : a ^ 2 = 1 := calc
      a ^ 2 = a⁻¹ * a := by rw [pow_two, hfix]
      _ = 1 := inv_mul_cancel a
    let _ : Fact (Nat.Prime 2) := ⟨Nat.prime_two⟩
    exact ⟨a, orderOf_eq_prime hsq (Finset.mem_erase.mp ha).1⟩
  obtain ⟨k, hk⟩ := even_card_of_involution Inv.inv inv_inv nonidentity hclosed hfree
  obtain ⟨n, hn⟩ := hEven
  have hcard : nonidentity.card + 1 = Fintype.card G := by
    simpa only [nonidentity, Finset.card_univ] using
      Finset.card_erase_add_one (Finset.mem_univ (1 : G))
  omega

#print axioms exercise11
#print axioms exercise16
#print axioms exercise15
#print axioms exercise26
#print axioms exercise27
#print axioms exercise25
#print axioms exercise23
#print axioms exercise22
#print axioms exercise31

end AI4Algebra.Benchmarks.Gold.Selected
