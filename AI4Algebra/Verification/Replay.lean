import AI4Algebra.Bridge.Main

/-! The standalone proof's tactic accepts exactly a structured bridge action. -/

namespace AI4Algebra.Verification

open Lean Elab Meta Tactic

private def withoutRecursionLocals (goal : MVarId) : MetaM MVarId := goal.withContext do
  let auxiliary := (← getLCtx).foldl (fun ids decl =>
    if decl.kind == .auxDecl then ids.push decl.fvarId else ids) #[]
  auxiliary.foldrM (fun id current => current.clear id) goal

elab "ai4algebra_step " payload:str : tactic => do
  let action : AI4Algebra.Bridge.Action ←
    ofExcept <| Json.parse payload.getString >>= fromJson?
  -- The theorem elaborator installs a recursive reference that the observer never sees.
  -- Clear it before interpreting the saved goal and local positions.
  let trustedGoals ← (← getUnsolvedGoals).mapM fun goal => withoutRecursionLocals goal
  setGoals trustedGoals
  withoutRecover <| AI4Algebra.Bridge.applyAction action

end AI4Algebra.Verification
