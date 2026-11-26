import AI4Algebra.Benchmarks.Gold.SelectedGroups

set_option autoImplicit false

-- Reference-only check: this deliberately imports the protected reference proof.
theorem AI4Algebra.Benchmarks.SelectedReferenceRecord.exercise27.{u} :
    ? (G : Type u) [Group G] (x : G), ∃ K : Subgroup G, (K : Set G) = {y : G | ∃ n : ℤ, x ^ n = y} :=
  @AI4Algebra.Benchmarks.Gold.Selected.exercise27
