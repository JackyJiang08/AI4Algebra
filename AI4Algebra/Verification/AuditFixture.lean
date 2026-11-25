import AI4Algebra.Verification.GoldFixture

/-! Test-only dependencies with known audit outcomes. -/

namespace AI4Algebra.Verification.AuditFixture

axiom newAxiom : True

theorem axiomWrapper : True := newAxiom

theorem admitted : True := by
  sorry

theorem sorryWrapper : True := admitted

theorem deniedAnswer : True := True.intro

theorem deniedWrapper : True := deniedAnswer

theorem deniedRewrite (n : Nat) : 0 + n = n := Nat.zero_add n

theorem simpWrapper (n : Nat) : 0 + n = n := deniedRewrite n

end AI4Algebra.Verification.AuditFixture
