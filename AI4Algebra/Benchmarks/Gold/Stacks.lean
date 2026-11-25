import Mathlib.LinearAlgebra.TensorProduct.Map
import Mathlib.RingTheory.Finiteness.Basic
import Mathlib.RingTheory.Spectrum.Prime.RingHom

/- Protected proof fixtures for the Stacks pilot. -/

set_option autoImplicit false
set_option warningAsError true

namespace AI4Algebra.Benchmarks.Gold.Stacks

universe u v w x y

theorem quotient_spectrum_image (R : Type u) [CommRing R] (I : Ideal R) :
    Set.range (PrimeSpectrum.comap (Ideal.Quotient.mk I)) =
      PrimeSpectrum.zeroLocus (I : Set R) := by
  rw [range_comap_of_surjective]
  · rw [Ideal.mk_ker]
  · exact Ideal.Quotient.mk_surjective

theorem finite_over_extension (R : Type u) (S : Type v) (M : Type w)
    [CommRing R] [CommRing S] [Algebra R S] [AddCommGroup M] [Module R M]
    [Module S M] [IsScalarTower R S M] [Module.Finite R S] :
    Module.Finite R M ↔ Module.Finite S M := by
  constructor
  · intro h
    exact Module.Finite.of_restrictScalars_finite R S M
  · intro h
    exact Module.Finite.trans S M

theorem universal_injective_composition (R : Type u) [CommRing R] (M : Type v) (N : Type w)
    (P : Type x)
    [AddCommGroup M] [Module R M] [AddCommGroup N] [Module R N]
    [AddCommGroup P] [Module R P]
    (f : M →ₗ[R] N) (g : N →ₗ[R] P)
    (hf : ∀ (Q : Type y) [AddCommGroup Q] [Module R Q], Function.Injective (f.rTensor Q))
    (hg : ∀ (Q : Type y) [AddCommGroup Q] [Module R Q], Function.Injective (g.rTensor Q))
    (Q : Type y) [AddCommGroup Q] [Module R Q] :
    Function.Injective ((g.comp f).rTensor Q) := by
  rw [LinearMap.rTensor_comp, LinearMap.coe_comp]
  exact (hg Q).comp (hf Q)

end AI4Algebra.Benchmarks.Gold.Stacks
