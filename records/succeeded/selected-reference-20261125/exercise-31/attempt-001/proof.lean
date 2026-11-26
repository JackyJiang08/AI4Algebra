import AI4Algebra.Benchmarks.Gold.SelectedGroups

set_option autoImplicit false

-- Reference-only check: this deliberately imports the protected reference proof.
theorem AI4Algebra.Benchmarks.SelectedReferenceRecord.exercise31.{u} :
    ? (G : Type u) [Group G] [Fintype G] (hEven : Even (Fintype.card G)), ∃ a : G, orderOf a = 2 :=
  @AI4Algebra.Benchmarks.Gold.Selected.exercise31
