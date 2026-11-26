import AI4Algebra.Benchmarks.SelectedDefinitions
import Mathlib.Algebra.GroupWithZero.Units.Basic
import Mathlib.NumberTheory.Real.Irrational
import Mathlib.Tactic.LinearCombination

/- Protected reference proof for selected Exercise 9. -/
set_option autoImplicit false
set_option warningAsError true

namespace AI4Algebra.Benchmarks.Gold.Selected

open AI4Algebra.Benchmarks.Selected

private theorem sqrt_two_sq : Real.sqrt 2 ^ 2 = 2 :=
  Real.sq_sqrt (by norm_num)

private theorem mul_conjugate (a b : ℚ) :
    ((a : ℝ) + (b : ℝ) * Real.sqrt 2) * ((a : ℝ) - (b : ℝ) * Real.sqrt 2) =
      (a : ℝ) ^ 2 - 2 * (b : ℝ) ^ 2 := by
  linear_combination -((b : ℝ) ^ 2) * sqrt_two_sq

private theorem denominator_ne_zero (a b : ℚ)
    (hx : (a : ℝ) + (b : ℝ) * Real.sqrt 2 ≠ 0) :
    (a : ℝ) ^ 2 - 2 * (b : ℝ) ^ 2 ≠ 0 := by
  intro hz
  have hconj : (a : ℝ) - (b : ℝ) * Real.sqrt 2 = 0 :=
    (mul_eq_zero.mp ((mul_conjugate a b).trans hz)).resolve_left hx
  by_cases hb : b = 0
  · subst b
    apply hx
    simpa using hconj
  · have hbReal : (b : ℝ) ≠ 0 := by exact_mod_cast hb
    refine irrational_sqrt_two ⟨a / b, ?_⟩
    rw [Rat.cast_div, div_eq_iff hbReal, mul_comm]
    exact sub_eq_zero.mp hconj

theorem exercise9 :
    (∃ A : AddSubgroup ℝ, (A : Set ℝ) = quadraticSet) ∧
      (∃ M : Subgroup ℝˣ, (M : Set ℝˣ) = {x : ℝˣ | (x : ℝ) ∈ quadraticSet}) := by
  constructor
  · refine ⟨{ carrier := quadraticSet, add_mem' := ?_, zero_mem' := ?_, neg_mem' := ?_ }, rfl⟩
    · rintro x y ⟨a, b, rfl⟩ ⟨c, d, rfl⟩
      refine ⟨a + c, b + d, ?_⟩
      push_cast
      ring
    · exact ⟨0, 0, by simp⟩
    · rintro x ⟨a, b, rfl⟩
      refine ⟨-a, -b, ?_⟩
      push_cast
      ring
  · refine ⟨{ carrier := {x : ℝˣ | (x : ℝ) ∈ quadraticSet}
              mul_mem' := ?_, one_mem' := ?_, inv_mem' := ?_ }, rfl⟩
    · rintro x y ⟨a, b, hx⟩ ⟨c, d, hy⟩
      refine ⟨a * c + 2 * b * d, a * d + b * c, ?_⟩
      rw [Units.val_mul, hx, hy]
      push_cast
      linear_combination (b : ℝ) * (d : ℝ) * sqrt_two_sq
    · exact ⟨1, 0, by simp⟩
    · rintro x ⟨a, b, hx⟩
      have hx₀ : (a : ℝ) + (b : ℝ) * Real.sqrt 2 ≠ 0 := hx ▸ x.ne_zero
      let d : ℚ := a ^ 2 - 2 * b ^ 2
      have hdCast : (d : ℝ) = (a : ℝ) ^ 2 - 2 * (b : ℝ) ^ 2 := by
        dsimp [d]
        push_cast
      have hdReal : (d : ℝ) ≠ 0 := hdCast.symm ▸ denominator_ne_zero a b hx₀
      refine ⟨a / d, -b / d, x.inv_eq_of_mul_eq_one_right ?_⟩
      push_cast
      rw [hx]
      have hconjDiv : (a : ℝ) / (d : ℝ) + (-(b : ℝ) / (d : ℝ)) * Real.sqrt 2 =
          ((a : ℝ) - (b : ℝ) * Real.sqrt 2) / (d : ℝ) := by
        simp only [div_eq_mul_inv]
        ring
      rw [hconjDiv, ← mul_div_assoc, mul_conjugate]
      rw [← hdCast, div_self hdReal]

end AI4Algebra.Benchmarks.Gold.Selected
