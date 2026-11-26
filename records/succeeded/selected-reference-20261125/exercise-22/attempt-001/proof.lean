import AI4Algebra.Benchmarks.Gold.SelectedGroups

set_option autoImplicit false

-- Reference-only check: this deliberately imports the protected reference proof.
theorem AI4Algebra.Benchmarks.SelectedReferenceRecord.exercise22.{u} :
    ? (G : Type u) [Group G], (∀ x g : G, orderOf x = orderOf (g⁻¹ * x * g)) ∧ (∀ a b : G, orderOf (a * b) = orderOf (b * a)) :=
  @AI4Algebra.Benchmarks.Gold.Selected.exercise22
