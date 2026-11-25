"""Applicability and typed arguments on the pinned Lean observer."""

from pathlib import Path

import pytest

from ai4algebra.candidates import (
    CandidateGenerator,
    LemmaRule,
    PremiseIndex,
    elementary_premise_index,
)
from ai4algebra.config import Limits
from ai4algebra.contracts import Argument, Candidate, Problem, SourceRef, digest_json
from ai4algebra.corpus import Corpus
from ai4algebra.lean_bridge import LeanBridge
from ai4algebra.verification import EligibilityPolicy

pytestmark = pytest.mark.lean
_ROOT = Path(__file__).resolve().parents[2]
_LIMITS = Limits(
    max_candidates=8, step_timeout_seconds=60.0, task_timeout_seconds=300.0
)
_NAT_SUCC = LemmaRule(
    name="Nat.succ.inj",
    module="Init.Data.Nat.Basic",
    statement="∀ {m n : ℕ}, m.succ = n.succ → m = n",
    expression=(
        '["forall","implicit",["const","Nat",[]],["forall","implicit",["const","Nat",[]],'
        '["forall","explicit",["app",["app",["app",["const","Eq",[["succ",["zero"]]]],'
        '["const","Nat",[]]],["app",["const","Nat.succ",[]],["bvar",1]]],'
        '["app",["const","Nat.succ",[]],["bvar",0]]],'
        '["app",["app",["app",["const","Eq",[["succ",["zero"]]]],["const","Nat",[]]],'
        '["bvar",2]],["bvar",1]]]]]'
    ),
)
_SUBSINGLETON = LemmaRule(
    name="Subsingleton.elim",
    module="Init.Prelude",
    statement="∀ {α : Sort u} [Subsingleton α] (a b : α), a = b",
    expression=(
        '["forall","implicit",["sort",["param","u"]],'
        '["forall","instance",["app",["const","Subsingleton",[["param","u"]]],["bvar",0]],'
        '["forall","explicit",["bvar",1],["forall","explicit",["bvar",2],'
        '["app",["app",["app",["const","Eq",[["param","u"]]],["bvar",3]],'
        '["bvar",1]],["bvar",0]]]]]]'
    ),
)


def _problem(statement: str, binders: tuple[str, ...]) -> Problem:
    return Problem(
        task_id="applicability",
        family_id="applicability",
        split="train",
        source=SourceRef(
            kind="fixture",
            source_id="applicability",
            revision="1",
            location="tests/lean/test_applicability.py",
            content_digest=digest_json(statement),
            attribution="AI4Algebra",
            license_ref="MIT",
        ),
        informal_statement=statement,
        imports=(),
        lean_name="ai4algebra_applicability",
        lean_statement=statement,
        binders=binders,
        mapping_evidence_id="applicability",
    )


def _generator(
    problem: Problem,
    bridge: LeanBridge,
    environment: str,
    rule: LemmaRule = _NAT_SUCC,
) -> CandidateGenerator:
    policy = EligibilityPolicy(
        task_id=problem.task_id,
        statement_digest=problem.statement_digest,
        allowed_imports=problem.imports,
        allowed_declarations=(rule.name,),
    )
    index = PremiseIndex(environment_digest=environment, imports=(), rules=(rule,))
    return CandidateGenerator(problem, policy, bridge, premise_index=index)


def test_lean_apply_exposes_missing_premise_and_retains_sibling() -> None:
    bridge = LeanBridge(_ROOT)
    problem = _problem("m = n ∧ True", ("(m n : Nat)",))
    root, initial = bridge.open(problem, _LIMITS)
    try:
        split = bridge.step(root, Candidate(operation="constructor", goal_id="g0"))
        assert split.observation is not None and split.snapshot is not None, (
            split.diagnostics
        )
        generator = _generator(problem, bridge, root.environment_digest)
        result = generator.generate(
            split.snapshot, split.observation, _LIMITS, probe_limit=1
        )
        first = result.probes[0]
        assert result.probe_calls == 1
        assert (
            first.candidate.operation == "apply"
            and first.candidate.lemma == "Nat.succ.inj"
        )
        assert (
            first.eligible
            and first.result is not None
            and first.result.observation is not None
        )
        assert tuple(goal.target for goal in first.result.observation.goals) == (
            "m.succ = n.succ",
            "True",
        )
        assert tuple(
            goal.target
            for goal in result.candidate_contexts[first.candidate_id].side_goals
        ) == ("m.succ = n.succ",)
        assert bridge.observe(split.snapshot) == split.observation
        assert bridge.observe(root) == initial
        cached = generator.generate(
            split.snapshot, split.observation, _LIMITS, probe_limit=0
        )
        assert cached.probes[0].reused and cached.probes[0].result == first.result
        assert cached.probe_calls == 0
    finally:
        bridge.close(root.session_id)


def test_lean_exact_checks_instantiated_local_premise() -> None:
    bridge = LeanBridge(_ROOT)
    problem = _problem("m = n", ("(m n : Nat)", "(h : m.succ = n.succ)"))
    root, initial = bridge.open(problem, _LIMITS)
    try:
        result = _generator(problem, bridge, root.environment_digest).generate(
            root, initial, _LIMITS, probe_limit=1
        )
        first = result.probes[0]
        assert (
            first.candidate.operation == "exact"
            and first.candidate.lemma == "Nat.succ.inj"
        )
        assert first.candidate.arguments == (Argument(kind="local", reference="l2"),)
        assert first.status == "closed" and first.eligible, first.result
        assert bridge.observe(root) == initial
    finally:
        bridge.close(root.session_id)


def test_lean_probe_rejects_a_missing_typeclass_instance() -> None:
    bridge = LeanBridge(_ROOT)
    problem = _problem("m = n", ("(m n : Nat)",))
    root, initial = bridge.open(problem, _LIMITS)
    try:
        result = _generator(
            problem, bridge, root.environment_digest, _SUBSINGLETON
        ).generate(root, initial, _LIMITS, probe_limit=1)
        first = result.probes[0]
        assert (
            first.candidate.operation == "exact"
            and first.candidate.lemma == "Subsingleton.elim"
        )
        assert first.status == "rejected" and not first.eligible, first.result
        assert first.result is not None and first.result.observation == initial
        assert any(
            "failed to synthesize" in diagnostic and "Subsingleton" in diagnostic
            for diagnostic in first.result.diagnostics
        )
    finally:
        bridge.close(root.session_id)


def test_pinned_elementary_premises_simplify_without_global_simp() -> None:
    corpus = Corpus.open(_ROOT / "data/manifests/elementary.json")
    problem = next(
        problem
        for problem in corpus.problems()
        if problem.task_id == "group-inverse-identity"
    )
    bridge = LeanBridge(_ROOT)
    root, observation = bridge.open(problem, _LIMITS)
    try:
        generator = CandidateGenerator(
            problem,
            corpus.eligibility_policy(problem),
            bridge,
            premise_index=elementary_premise_index(corpus, problem, _ROOT),
        )
        generated = generator.generate(root, observation, _LIMITS, probe_limit=1)
        first = generated.probes[0]
        assert first.candidate.operation == "simp_only", first.candidate
        assert first.candidate.simp_lemmas == ("mul_inv_cancel",)
        assert first.status == "advanced", first.result
        assert first.result is not None and first.result.observation is not None
        successor = generator.generate(
            first.result.observation.snapshot,
            first.result.observation,
            _LIMITS,
            probe_limit=1,
        )
        assert successor.probes[0].status == "closed", successor.probes[0].result
    finally:
        bridge.close(root.session_id)
