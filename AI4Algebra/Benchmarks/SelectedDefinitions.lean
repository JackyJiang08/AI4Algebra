import Mathlib.Algebra.Group.Subgroup.Defs
import Mathlib.Analysis.Real.Sqrt

set_option autoImplicit false

namespace AI4Algebra.Benchmarks.Selected

/-- The real numbers of the form `a + b * √2`, with rational coefficients. -/
def quadraticSet : Set ℝ :=
  {x | ∃ a b : ℚ, x = (a : ℝ) + (b : ℝ) * Real.sqrt 2}

end AI4Algebra.Benchmarks.Selected
