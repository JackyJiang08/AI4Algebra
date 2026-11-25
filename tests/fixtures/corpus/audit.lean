open Lean Elab Command Meta

private def normalizedUniverses (info : ConstantInfo) (type : Expr) : Expr :=
  type.instantiateLevelParams info.levelParams
    (info.levelParams.zipIdx.map fun (_, i) => .param (Name.mkSimple s!"u{i}"))

private partial def telescopeKinds : Expr → List BinderInfo
  | .forallE _ _ rest kind => kind :: telescopeKinds rest
  | _ => []

def checkExercise (source manifest mapping referenceProof : Name) : CommandElabM Unit := do
  let env ← getEnv
  let some sourceInfo := env.find? source | throwError "missing source type {source}"
  let some manifestInfo := env.find? manifest | throwError "missing manifest type {manifest}"
  let some mappingInfo := env.find? mapping | throwError "missing evidence type {mapping}"
  let some proofInfo := env.find? referenceProof | throwError "missing reference proof {referenceProof}"
  let expected := normalizedUniverses sourceInfo sourceInfo.value!
  let proposed := normalizedUniverses manifestInfo manifestInfo.value!
  let reviewed := normalizedUniverses mappingInfo mappingInfo.value!
  let proven := normalizedUniverses proofInfo proofInfo.type
  for actual in [proposed, reviewed, proven] do
    unless telescopeKinds expected == telescopeKinds actual &&
        (← liftTermElabM <| isDefEq expected actual) do
      throwError "source type mismatch for {manifest}"
  let axioms ← Lean.collectAxioms referenceProof
  unless axioms.all (fun name => name == `propext || name == `Classical.choice ||
      name == `Quot.sound) do
    throwError "unapproved axiom in {referenceProof}: {axioms}"
  logInfo m!"TYPE_KEY {manifest} {hash expected}"

private partial def dependencies (env : Environment) (pending : List Name) (seen : NameSet) :
    NameSet :=
  match pending with
  | [] => seen
  | name :: rest =>
    if seen.contains name then
      dependencies env rest seen
    else
      let next := ((env.find? name).map fun info => info.getUsedConstantsAsSet.toList).getD []
      dependencies env (next ++ rest) (seen.insert name)

def checkDependencies (tracked : List Name) (name : Name) : CommandElabM Unit := do
  let env ← getEnv
  unless env.contains name do
    throwError "missing declared premise or alias {name}"
  let closure := dependencies env [name] {}
  let relevant := tracked.filter fun dependency => dependency != name && closure.contains dependency
  let home := (env.getModuleIdxFor? name).bind (env.header.moduleNames[·]?)
  logInfo m!"DEPENDENCIES {name} | {home.getD .anonymous} | {String.intercalate "," (relevant.map Name.toString)}"

def checkDistinctFamilies (first second : Name) : CommandElabM Unit := do
  let env ← getEnv
  let some firstInfo := env.find? first | throwError "missing exercise {first}"
  let some secondInfo := env.find? second | throwError "missing exercise {second}"
  if ← liftTermElabM <| isDefEq (normalizedUniverses firstInfo firstInfo.value!)
      (normalizedUniverses secondInfo secondInfo.value!) then
    throwError "Lean-equivalent reference types assigned separate families {first} and {second}"

section

variable {G : Type} [Group G] (a b : G)

-- The principal answer alias has only a parenthesis change.
example : (a * b * b⁻¹ = a) ↔ (a * (b * b⁻¹) = a) := by
  rw [mul_assoc]

example : a * b * b⁻¹ = a := mul_inv_cancel_right a b

-- Mathlib's division notation gives the same reassociated statement.
example : (a * b / b = a) ↔ (a * (b * b⁻¹) = a) := by
  rw [div_eq_mul_inv, mul_assoc]

example : a * b / b = a := mul_div_cancel_right a b

end
