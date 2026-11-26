import Mathlib.Data.ZMod.Basic
import AI4Algebra.Bridge.Main
open Lean Elab Meta
run_cmd Lean.Elab.Command.liftTermElabM do
  let env ← getEnv
  for name in ([``addOrderOf_eq_iff, ``Nat.zero_lt_succ] : List Name) do
    let info ← getConstInfo name
    let mut pending := info.getUsedConstantsAsSet.toList
    let mut seen : NameSet := {}
    while let current :: remaining := pending do
      pending := remaining
      if seen.contains current then continue
      if seen.size >= 8192 then throwError "signature dependency limit"
      seen := seen.insert current
      let some dependency := env.checked.get.find? current
        | throwError "missing dependency {current}"
      pending := dependency.getUsedConstantsAsSet.toList ++ pending
    let some moduleIndex := env.getModuleIdxFor? name
      | throwError "missing declaration module"
    let moduleName := env.allImportedModuleNames[moduleIndex.toNat]!
    let output := Json.mkObj [
      ("name", toJson name.toString),
      ("statement", toJson (← ppExpr info.type).pretty),
      ("expression", toJson (AI4Algebra.Bridge.encodeExpr {} info.type).compress),
      ("module", toJson moduleName.toString),
      ("dependencies", toJson (seen.toList.map Name.toString))]
    IO.println ("PREMISE:" ++ output.compress)
