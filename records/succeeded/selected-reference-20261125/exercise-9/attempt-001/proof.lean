import AI4Algebra.Benchmarks.Gold.SelectedQuadratic

set_option autoImplicit false

-- Reference-only check: this deliberately imports the protected reference proof.
theorem AI4Algebra.Benchmarks.SelectedReferenceRecord.exercise9 :
    (∃ A : AddSubgroup ℝ, (A : Set ℝ) = AI4Algebra.Benchmarks.Selected.quadraticSet) ∧ (∃ M : Subgroup ℝˣ, (M : Set ℝˣ) = {x : ℝˣ | (x : ℝ) ∈ AI4Algebra.Benchmarks.Selected.quadraticSet}) :=
  @AI4Algebra.Benchmarks.Gold.Selected.exercise9
