import Mathlib.LinearAlgebra.TensorProduct.Map
import Mathlib.RingTheory.Finiteness.Basic
import Mathlib.RingTheory.Spectrum.Prime.RingHom

/- Curated source types for selected claims of the pinned Stacks Project. -/

set_option autoImplicit false
set_option linter.unusedVariables false

namespace AI4Algebra.Benchmarks.StacksStatements

universe u v w x y

/-- Tag 00E5, only the image of the map on points. -/
def quotient_spectrum_image : Prop :=
  ∀ (A : Type u) [CommRing A] (J : Ideal A),
    Set.range (PrimeSpectrum.comap (Ideal.Quotient.mk J)) =
      PrimeSpectrum.zeroLocus (J : Set A)

/-- Tag 00GJ, both directions of finiteness for a finite ring extension. -/
def finite_over_extension : Prop :=
  ∀ (A : Type u) (B : Type v) (N : Type w) [CommRing A] [CommRing B]
    [Algebra A B] [AddCommGroup N] [Module A N] [Module B N]
    [IsScalarTower A B N] [Module.Finite A B],
    Module.Finite A N ↔ Module.Finite B N

/-- Tag 05CI, expanding the definition of universally injective for each map. -/
def universal_injective_composition : Prop :=
  ∀ (A : Type u) [CommRing A] (L : Type v) (M : Type w) (N : Type x)
    [AddCommGroup L] [Module A L] [AddCommGroup M] [Module A M]
    [AddCommGroup N] [Module A N]
    (f : L →ₗ[A] M) (g : M →ₗ[A] N)
    (_ : ∀ (P : Type y) [AddCommGroup P] [Module A P], Function.Injective (f.rTensor P))
    (_ : ∀ (P : Type y) [AddCommGroup P] [Module A P], Function.Injective (g.rTensor P))
    (P : Type y) [AddCommGroup P] [Module A P],
    Function.Injective ((g.comp f).rTensor P)

end AI4Algebra.Benchmarks.StacksStatements
