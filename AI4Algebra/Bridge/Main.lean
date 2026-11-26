import Lean

/-! A one-request proof observer. The caller replays a prefix in a new process for each step. -/

namespace AI4Algebra.Bridge

open Lean Elab Meta Tactic

structure Argument where
  kind : String
  reference : String
  deriving FromJson

structure Action where
  operation : String
  goal_id : String
  lemma : Option String
  local_id : Option String
  arguments : Array Argument
  direction : String
  location : Option String
  simp_lemmas : Array String
  deriving FromJson

structure Request where
  schema_version : Nat
  request_id : String
  session_id : String
  operation : String
  environment_digest : String
  snapshot_id : String
  prefix_digest : String
  statement_digest : String
  imports : Array String
  theorem_name : String
  universes : Array String
  binders : Array String
  statement : String
  «prefix» : Array Action
  candidate : Option Action
  deriving FromJson

structure Hypothesis where
  schema_version : Nat := 1
  local_id : String
  binder_kind : String
  name : String
  type_text : String
  expression : String
  value : Option String
  deriving ToJson

structure Goal where
  schema_version : Nat := 1
  goal_id : String
  target : String
  expression : String
  hypotheses : Array Hypothesis
  deriving ToJson

private def goalId (index : Nat) : String := s!"g{index}"
private def localId (index : Nat) : String := s!"l{index}"

private def locals : MetaM (Array LocalDecl) := do
  return (← getLCtx).foldl (fun result decl => result.push decl) #[]

private def binderKind : BinderInfo → String
  | .default => "explicit"
  | .implicit => "implicit"
  | .strictImplicit => "strict_implicit"
  | .instImplicit => "instance"

private partial def encodeLevel : Level → Json
  | .zero => toJson #["zero"]
  | .succ level => Json.arr #[toJson "succ", encodeLevel level]
  | .max lhs rhs => Json.arr #[toJson "max", encodeLevel lhs, encodeLevel rhs]
  | .imax lhs rhs => Json.arr #[toJson "imax", encodeLevel lhs, encodeLevel rhs]
  | .param name => toJson #["param", name.toString]
  | .mvar id => toJson #["mvar", id.name.toString]

partial def encodeExpr (ids : FVarIdMap Nat) : Expr → Json
  | .bvar index => Json.arr #[toJson "bvar", toJson index]
  | .fvar id => match ids.get? id with
    | some index => Json.arr #[toJson "local", toJson index]
    | none => toJson #["free", id.name.toString]
  | .mvar id => toJson #["mvar", id.name.toString]
  | .sort level => Json.arr #[toJson "sort", encodeLevel level]
  | .const name levels => Json.arr #[toJson "const", toJson name, toJson (levels.map encodeLevel)]
  | .app fn arg => Json.arr #[toJson "app", encodeExpr ids fn, encodeExpr ids arg]
  | .lam _ type body info =>
    Json.arr #[toJson "lam", toJson (binderKind info), encodeExpr ids type, encodeExpr ids body]
  | .forallE _ type body info =>
    Json.arr #[toJson "forall", toJson (binderKind info), encodeExpr ids type, encodeExpr ids body]
  | .letE _ type value body nondep =>
    Json.arr #[toJson "let", encodeExpr ids type, encodeExpr ids value, encodeExpr ids body,
      toJson nondep]
  | .lit (.natVal n) => Json.arr #[toJson "nat", toJson n]
  | .lit (.strVal s) => toJson #["string", s]
  | .mdata _ e => encodeExpr ids e
  | .proj name index e => Json.arr #[toJson "proj", toJson name, toJson index, encodeExpr ids e]

private def exportGoal (index : Nat) (g : MVarId) : MetaM Goal := g.withContext do
  let ctx ← locals
  let mut ids : FVarIdMap Nat := {}
  for i in [:ctx.size] do
    ids := ids.insert ctx[i]!.fvarId i
  let hypotheses ← ctx.mapIdxM fun i decl => do
    let type ← instantiateMVars decl.type
    let value ← decl.value?.mapM fun expr => do
      return (encodeExpr ids (← instantiateMVars expr)).compress
    return {
      local_id := localId i
      binder_kind := binderKind decl.binderInfo
      name := decl.userName.eraseMacroScopes.toString
      type_text := (← ppExpr type).pretty
      expression := (encodeExpr ids type).compress
      value
    }
  let target ← instantiateMVars (← g.getType)
  return {
    goal_id := goalId index
    target := (← ppExpr target).pretty
    expression := (encodeExpr ids target).compress
    hypotheses
  }

private def resolveLocal (id : String) : TacticM LocalDecl := do
  let ctx ← locals
  for i in [:ctx.size] do
    if localId i == id then return ctx[i]!
  throwError "unknown local '{id}'"

private def resolveLemma (name : String) : TacticM Ident := do
  let resolved := name.toName
  unless (← getEnv).contains resolved do
    throwError "unknown declaration '{name}'"
  return mkCIdent resolved

private def localTerm (id : String) : TacticM Term := do
  Term.exprToSyntax (mkFVar (← resolveLocal id).fvarId)

private def lemmaTerm (name : String) : TacticM Term := do
  let ident ← resolveLemma name
  `($ident:ident)

private def operand (action : Action) : TacticM Term := do
  match action.lemma, action.local_id with
  | some lemma, none =>
    let head ← lemmaTerm lemma
    let args ← action.arguments.mapM fun arg =>
      match arg.kind with
      | "local" => localTerm arg.reference
      | "lemma" => lemmaTerm arg.reference
      | _ => throwError "invalid argument kind"
    if args.isEmpty then return head
    `($head $args*)
  | none, some id => localTerm id
  | _, _ => throwError "expected exactly one tactic operand"

private def actionSyntax (action : Action) : TacticM (TSyntax `tactic) := do
  match action.operation with
  | "decide" => `(tactic| set_option synthInstance.maxSize 4096 in decide)
  | "assumption" => `(tactic| assumption)
  | "reflexivity" => `(tactic| rfl)
  | "intro" => `(tactic| intro)
  | "constructor" => `(tactic| constructor)
  | "exact" => `(tactic| exact $(← operand action))
  | "apply" => `(tactic| apply $(← operand action))
  | "rewrite" =>
    let tm ← operand action
    let rule ← match action.direction with
      | "forward" => `(Parser.Tactic.rwRule| $tm:term)
      | "backward" => `(Parser.Tactic.rwRule| ← $tm:term)
      | _ => throwError "unknown rewrite direction"
    if let some location := action.location then
      let localDecl ← resolveLocal location
      let name := localDecl.userName
      unless (← getLCtx).findFromUserName? name |>.any (·.fvarId == localDecl.fvarId) do
        throwError "rewrite location is shadowed"
      `(tactic| rw [$rule] at $(mkIdent name):ident)
    else
      `(tactic| rw [$rule])
  | "simp_only" =>
    if action.simp_lemmas.isEmpty then throwError "simp_only requires lemmas"
    let lemmas ← action.simp_lemmas.mapM fun name => do
      let lemma ← lemmaTerm name
      -- Treat propositions as proof expressions. Global simp preprocessing may
      -- otherwise emit auxiliary declarations, violating standalone replay's
      -- single-declaration contract. Keep definition unfolding unchanged.
      let info ← getConstInfo name.toName
      if ← isProp info.type then
        let identifier ← resolveLemma name
        let proof ← `(term| @$identifier:ident)
        `(Parser.Tactic.simpLemma| (_root_.id $proof:term))
      else
        `(Parser.Tactic.simpLemma| $lemma:term)
    `(tactic| simp only [$lemmas,*])
  | _ => throwError "unknown action"

def applyAction (action : Action) : TacticM Unit := do
  let goals := (← getUnsolvedGoals).toArray
  let some index := (List.range goals.size).find? (goalId · == action.goal_id)
    | throwError "unknown goal '{action.goal_id}'"
  let target := goals[index]!
  setGoals [target]
  target.withContext do
    let tactic ← actionSyntax action
    withoutRecover <| evalTactic tactic
  let newGoals ← getUnsolvedGoals
  setGoals ((goals.extract 0 index).toList ++ newGoals ++ (goals.extract (index + 1)).toList)

private def verifiedGoals (root : Expr) : TacticM (Array MVarId) := do
  Term.synthesizeSyntheticMVarsNoPostponing
  let goals := (← getUnsolvedGoals).toArray
  let proof ← instantiateMVars root
  if proof.hasSorry then throwError "observer proof contains an admitted goal"
  let obligations ← proof.getMVarDependencies
  unless obligations.toList.all goals.contains do
    throwError "observer proof contains untracked obligations"
  if goals.isEmpty && proof.hasMVar then
    throwError "observer proof contains unresolved metavariables"
  return goals

private def observation (root : Expr) : TacticM (Array Goal) := do
  (← verifiedGoals root).mapIdxM fun i goal => exportGoal i goal

private def wireResult (fields : List (String × Json)) : Json :=
  Json.mkObj (("schema_version", toJson 1) :: fields)

private def runActions (req : Request) (root : Expr) : TacticM Json := do
  for action in req.prefix do
    applyAction action
    discard <| verifiedGoals root
  let before ← observation root
  let some candidate := req.candidate
    | return wireResult [("status", toJson "observed"), ("goals", toJson before)]
  let saved ← Tactic.saveState
  try
    applyAction candidate
    let after ← observation root
    let status := if after.isEmpty then "closed" else "advanced"
    return wireResult [("status", toJson status), ("parent_goals", toJson before),
      ("goals", toJson after)]
  catch ex =>
    let diagnostic ← ex.toMessageData.toString
    saved.restore
    return wireResult [("status", toJson "rejected"), ("parent_goals", toJson before),
      ("diagnostic", toJson diagnostic)]

private partial def containsTactic (stx : Syntax) : Bool :=
  stx.getKind == ``Parser.Term.byTactic || stx.getKind == ``Parser.Term.binderTactic ||
    stx.getArgs.any containsTactic

private def parseTerm (text : String) : TermElabM Syntax := do
  let term ← ofExcept <| Parser.runParserCategory (← getEnv) `term text
  if containsTactic term then throwError "tactic terms are unsupported in the observer header"
  return term

private def elabStatement (req : Request) : TermElabM (Expr × Nat) := do
  let stmt ← parseTerm req.statement
  if req.binders.isEmpty then
    return (← Term.elabType stmt, 0)
  let binderText := String.intercalate " " req.binders.toList
  let binderTerm ← parseTerm s!"∀ {binderText}, True"
  match binderTerm with
  | `(term| ∀ $binders*, True) =>
    Term.elabBinders binders fun xs => do
      let target ← Term.elabType stmt
      Term.synthesizeSyntheticMVarsNoPostponing
      return (← mkForallFVars xs target, xs.size)
  | _ => throwError "expected theorem binders"

private def prove (req : Request) : TermElabM Json := do
  Term.withoutErrToSorry do
    Term.setLevelNames <| req.universes.toList.map String.toName
    let (type, binderCount) ← elabStatement req
    Term.synthesizeSyntheticMVarsNoPostponing
    let type ← Term.levelMVarToParam (← instantiateMVars type)
    unless !type.hasMVar && !type.hasSorry && (← isProp type) do
      throwError "expected a fully elaborated proposition"
    let name := req.theorem_name.toName
    if (← getEnv).contains name then throwError "theorem name already exists: {name}"
    forallBoundedTelescope type binderCount fun xs target => do
      let root ← mkFreshExprMVar target MetavarKind.syntheticOpaque
      let action := (runActions req root) { elaborator := .anonymous, recover := false }
      let (result, _) ← action.run { goals := [root.mvarId!] }
      let goals? := (result.getObjValAs? (Array Json) "goals").toOption
      if goals?.any Array.isEmpty then
        let value ← mkLambdaFVars xs (← instantiateMVars root)
        let value ← instantiateMVars value
        let levelParams := (collectLevelParams (collectLevelParams {} type) value).params.toList
        addDecl (.thmDecl { name, levelParams, type, value })
        let axioms ← Lean.collectAxioms name
        if axioms.contains ``sorryAx then
          throwError "observer proof depends on sorryAx"
      return result

private def reply (request : Request) (result : Json) : Json :=
  Json.mkObj [
    ("schema_version", toJson 1),
    ("request_id", toJson request.request_id),
    ("session_id", toJson request.session_id),
    ("environment_digest", toJson request.environment_digest),
    ("snapshot_id", toJson request.snapshot_id),
    ("prefix_digest", toJson request.prefix_digest),
    ("statement_digest", toJson request.statement_digest),
    ("lean_version", toJson Lean.versionString),
    ("result", result)
  ]

private def failure (message : String) : Json :=
  wireResult [("status", toJson "error"), ("diagnostic", toJson message)]

unsafe def run : IO UInt32 := do
  let stdin ← IO.getStdin
  let stdout ← IO.getStdout
  let input ← stdin.getLine
  match Json.parse input >>= fromJson? with
  | .error message =>
    (← IO.getStderr).putStrLn message
    return 1
  | .ok request =>
    if request.schema_version != 1 then return 1
    unless (request.operation == "observe" && request.candidate.isNone) ||
        (request.operation == "step" && request.candidate.isSome) do
      return 1
    let opts := Elab.async.set {} false
    let opts := opts.setBool `autoImplicit false
    let result ← try
      unless Lean.versionString == "4.34.0-rc1" &&
          Lean.githash == "3447a668783dbce1a8fdb97101dd067687b2b418" do
        throw <| IO.userError "Lean observer toolchain does not match the project pin"
      let sysroot ← match ← IO.getEnv "LEAN_SYSROOT" with
        | some path => pure (System.FilePath.mk path)
        | none => Lean.getBuildDir
      Lean.initSearchPath sysroot
      Lean.enableInitializersExecution
      let imports := (#[ "Lean" ] ++ request.imports).map (fun name => { module := name.toName })
      let env ← Lean.importModules imports opts (loadExts := true)
      let (out, core, _, _) ← (prove request).toIO
        { fileName := "<ai4algebra>", fileMap := default, options := opts }
        { env } {} {} {} {}
      if core.messages.hasErrors then
        pure <| failure (← core.messages.toList.head!.data.toString)
      else pure out
    catch error =>
      pure <| failure error.toString
    stdout.putStrLn (reply request result).compress
    return 0

end AI4Algebra.Bridge

unsafe def main : IO UInt32 := AI4Algebra.Bridge.run
