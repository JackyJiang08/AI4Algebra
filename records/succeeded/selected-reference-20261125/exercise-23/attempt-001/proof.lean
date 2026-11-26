import AI4Algebra.Benchmarks.Gold.SelectedGroups

set_option autoImplicit false

-- Reference-only check: this deliberately imports the protected reference proof.
theorem AI4Algebra.Benchmarks.SelectedReferenceRecord.exercise23.{u} :
    ? (G : Type u) [Group G] (x : G) (s t : ℕ) (hs : 0 < s) (ht : 0 < t) (horder : orderOf x = s * t), orderOf (x ^ s) = t :=
  @AI4Algebra.Benchmarks.Gold.Selected.exercise23
