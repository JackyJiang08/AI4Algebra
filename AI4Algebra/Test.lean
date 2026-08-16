import Mathlib

#check Subgroup
#check NormalSubgroup
#check Ideal
#check RingHom

example (G : Type*) [Group G] (x : G) : x * 1 = x := by
  simp
