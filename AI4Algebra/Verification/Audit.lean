import Lean

/-! Independently elaborate a complete theorem and inspect its checked declaration. -/

namespace AI4Algebra.Verification

open Lean Elab Meta

private structure Request where
  schema_version : Nat
  request_id : String
  certificate_digest : String
  imports : Array String
  theorem_name : String
  universes : Array String
  expected_type : String
  declaration : String
  forbidden_declarations : Array String
  forbidden_imports : Array String
  deriving FromJson

private structure AuditResult where
  schema_version : Nat := 1
  replay_passed : Bool
  type_passed : Option Bool := none
  axioms_passed : Option Bool := none
  dependencies_passed : Option Bool := none
  axioms : Array String := #[]
  dependencies : Array String := #[]
  diagnostics : Array String := #[]
  deriving ToJson

private structure DependencyAudit where
  names : Array Name := #[]
  violations : Array String := #[]
  incomplete : Array String := #[]

private def forbiddenModule (req : Request) (moduleName : Name) : Bool :=
  req.forbidden_imports.any fun prefixName => prefixName.toName.isPrefixOf moduleName

private def describePath (name : Name) (reversePath : List Name) : String :=
  String.intercalate " -> " ((name :: reversePath).reverse.map Name.toString)

private def auditDependencies (env : Environment) (req : Request) (root : Name) :
    DependencyAudit := Id.run do
  let forbidden := NameSet.ofList (req.forbidden_declarations.toList.map String.toName)
  let mut pending := [(root, ([] : List Name))]
  let mut seen : NameSet := {}
  let mut result : DependencyAudit := {}
  while let (name, path) :: remaining := pending do
    pending := remaining
    if name == root && !path.isEmpty then
      let message := s!"self-reference: {describePath name path}"
      result := { result with violations := result.violations.push message }
    if seen.contains name then continue
    seen := seen.insert name
    -- The pinned Stacks finite-module certificate has 4912 dependencies.
    if result.names.size >= 8192 then
      return { result with incomplete := result.incomplete.push "dependency audit limit reached" }
    if name != root then
      result := { result with names := result.names.push name }
    let dependencyModule? := env.getModuleIdxFor? name |>.bind
      (fun index => env.allImportedModuleNames[index.toNat]?)
    if (name != root && forbidden.contains name) || dependencyModule?.any (forbiddenModule req) then
      if result.violations.size < 32 then
        let message := s!"forbidden dependency: {describePath name path}"
        result := { result with violations := result.violations.push message }
    match env.checked.get.find? name with
    | none =>
      if result.incomplete.size < 32 then
        let message := s!"missing dependency body or signature: {describePath name path}"
        result := { result with incomplete := result.incomplete.push message }
    | some info =>
      for referenced in info.getUsedConstantsAsSet.toList do
        pending := (referenced, name :: path) :: pending
  return result

private partial def headerHasTactic (stx : Syntax) : Bool :=
  stx.getKind == ``Parser.Term.byTactic || stx.getKind == ``Parser.Term.binderTactic ||
    stx.getArgs.any headerHasTactic

private def parse (env : Environment) (category : Name) (source : String) : IO Syntax :=
  IO.ofExcept <| (Parser.runParserCategory env category source "<proof-audit>").mapError
    IO.userError

private def checkedType (environment : Environment) (opts : Options) (req : Request) :
    IO Expr := do
  let stx ← parse environment `term req.expected_type
  if headerHasTactic stx then
    throw <| IO.userError "tactic terms are unsupported in the trusted theorem header"
  let elaborate : TermElabM Expr := Term.withoutErrToSorry do
    Term.setLevelNames <| req.universes.toList.map String.toName
    let type ← Term.elabType stx
    Term.synthesizeSyntheticMVarsNoPostponing
    let type ← Term.levelMVarToParam (← instantiateMVars type)
    unless !type.hasMVar && !type.hasSorry && (← isProp type) do
      throwError "expected a fully elaborated proposition"
    return type
  let (expected, core, _, _) ← elaborate.toIO
    { fileName := "<trusted-header>", fileMap := FileMap.ofString req.expected_type, options := opts }
    { env := environment } {} {} {} {}
  if core.messages.hasErrors then
    throw <| IO.userError "trusted theorem header did not elaborate"
  return expected

private def matchingType (environment : Environment) (opts : Options) (actual expected : Expr) :
    IO Bool := do
  let canonical (expression : Expr) : Expr :=
    let levels := (collectLevelParams {} expression).params
    let replacements := levels.toList.zipIdx |>.map fun (_, i) =>
      Level.param (Name.str .anonymous s!"u{i}")
    expression.instantiateLevelParams levels.toList replacements
  let compare : MetaM Bool := isDefEq (canonical actual) (canonical expected)
  let (same, _, _) ← compare.toIO
    { fileName := "<type-audit>", fileMap := default, options := opts }
    { env := environment } {} {}
  return same

private def markReplayFailure (diagnostic : String) : AuditResult :=
  { replay_passed := false, diagnostics := #[diagnostic] }

private def compileProof (env : Environment) (opts : Options) (req : Request) :
    IO (Except AuditResult Environment) := do
  let parsed ← (try
    pure (.ok (← parse env `command req.declaration))
    catch error => pure (.error (markReplayFailure error.toString)) :
    IO (Except AuditResult Syntax))
  let .ok stx := parsed | return parsed.map (fun _ => env)
  unless stx.getKind == ``Parser.Command.declaration &&
      stx[1].getKind == ``Parser.Command.theorem do
    return .error (markReplayFailure "proof input must be exactly one theorem declaration")
  let command := Command.elabCommandTopLevel stx
  let ctx : Command.Context :=
    { fileName := "<standalone-proof>", fileMap := FileMap.ofString req.declaration,
      snap? := none, cancelTk? := none }
  let result ← EIO.toIO' ((command ctx).run (Command.mkState env (opts := opts)))
  let .ok (_, state) := result
    | throw <| IO.userError "theorem elaborator failed internally"
  if state.messages.hasErrors then
    let errors ← (state.messages.toList.filter (·.severity == .error)).take 8 |>.mapM
      (fun message => message.data.toString)
    return .error { replay_passed := false, diagnostics := errors.toArray }
  let additions := state.env.checked.get.constants.foldStage2
    (fun names name _ => if env.contains name then names else names.push name) #[]
  unless additions == #[req.theorem_name.toName] do
    return .error (markReplayFailure "unexpected declarations in standalone proof")
  return .ok state.env

private def axiomAllowlist : NameSet := NameSet.ofList [``propext, ``Classical.choice, ``Quot.sound]

private def finishAudit (env : Environment) (opts : Options) (req : Request) (expected : Expr) :
    IO AuditResult := do
  let name := req.theorem_name.toName
  let some (.thmInfo info) := env.checked.get.find? name
    | return markReplayFailure "the expected theorem is absent from the kernel environment"
  if info.type.hasMVar || info.value.hasMVar then
    return markReplayFailure "the proof has unresolved metavariables"
  let typePassed ← matchingType env opts info.type expected
  let collect : CoreM (Array Name) := Lean.collectAxioms name
  let (axioms, _) ← collect.toIO
    { fileName := "<axiom-audit>", fileMap := default, options := opts }
    { env }
  let deniedAxioms := axioms.filter (fun a => !axiomAllowlist.contains a)
  let axiomDiagnostics := deniedAxioms.map (fun a => s!"forbidden axiom: {a}")
  let dependencies := auditDependencies env req name
  let dependenciesPassed := if !dependencies.violations.isEmpty then some false
    else if dependencies.incomplete.isEmpty then some true
    else none
  let typeDiagnostics := if typePassed then #[] else #["the elaborated theorem type changed"]
  return {
    replay_passed := !info.value.hasSorry && !info.type.hasSorry
    type_passed := typePassed
    axioms_passed := deniedAxioms.isEmpty && !info.value.hasSorry && !info.type.hasSorry
    dependencies_passed := dependenciesPassed
    axioms := axioms.map Name.toString
    dependencies := (dependencies.names.qsort Name.lt).map Name.toString
    diagnostics := typeDiagnostics ++ axiomDiagnostics ++ dependencies.violations ++
      dependencies.incomplete
  }

private unsafe def audit (req : Request) : IO AuditResult := do
  let opts := (Elab.async.set {} false).setBool `autoImplicit false
  let sysroot ← match ← IO.getEnv "LEAN_SYSROOT" with
    | some path => pure (System.FilePath.mk path)
    | none => Lean.getBuildDir
  Lean.initSearchPath sysroot
  Lean.enableInitializersExecution
  let imports := (#["AI4Algebra.Verification.Replay"] ++ req.imports).map
    (fun name => { module := name.toName })
  let env ← Lean.importModules imports opts (loadExts := true)
  if env.contains req.theorem_name.toName then
    return markReplayFailure "theorem name is already present in the import environment"
  if let some moduleName := env.allImportedModuleNames.find? (forbiddenModule req) then
    return {
      replay_passed := false
      dependencies_passed := false
      diagnostics := #[s!"forbidden transitive import: {moduleName}"]
    }
  let expected ← checkedType env opts req
  match ← compileProof env opts req with
  | .error result => return result
  | .ok compiled => finishAudit compiled opts req expected

unsafe def auditMain : IO UInt32 := do
  let input ← (← IO.getStdin).getLine
  match Json.parse input >>= fromJson? with
  | .error message =>
    (← IO.getStderr).putStrLn message
    return 1
  | .ok req =>
    if req.schema_version != 1 then return 1
    let fields ← try
      unless Lean.versionString == "4.34.0-rc1" &&
          Lean.githash == "3447a668783dbce1a8fdb97101dd067687b2b418" do
        throw <| IO.userError "Lean verifier toolchain does not match the project pin"
      pure [("result", toJson (← audit req))]
    catch error =>
      pure [("error", toJson error.toString)]
    let response := Json.mkObj ([
      ("schema_version", toJson 1),
      ("request_id", toJson req.request_id),
      ("certificate_digest", toJson req.certificate_digest),
      ("lean_version", toJson Lean.versionString)
    ] ++ fields)
    (← IO.getStdout).putStrLn response.compress
    return 0

end AI4Algebra.Verification
