import AI4Algebra.Benchmarks.Gold.SelectedGroups

set_option autoImplicit false

-- Reference-only check: this deliberately imports the protected reference proof.
theorem AI4Algebra.Benchmarks.SelectedReferenceRecord.exercise15.{u} :
    ? (G : Type u) [Group G] (xs : List G), xs.prod⁻¹ = (xs.reverse.map (fun x : G => x⁻¹)).prod :=
  @AI4Algebra.Benchmarks.Gold.Selected.exercise15
