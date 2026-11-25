"""Independent proof compilation and dependency inspection on pinned Lean."""

import json
import subprocess
from pathlib import Path
from threading import Event

import pytest

from ai4algebra.contracts import Argument, Candidate, Problem, SourceRef, digest_json
from ai4algebra.lean_bridge.protocol import SubprocessWorker
from ai4algebra.verification import AXIOM_ALLOWLIST, EligibilityPolicy, Verifier

pytestmark = pytest.mark.lean
_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = "AI4Algebra.Verification.AuditFixture"


def _problem(
    statement: str,
    *,
    imports: tuple[str, ...] = (),
    binders: tuple[str, ...] = (),
    universes: tuple[str, ...] = (),
) -> Problem:
    return Problem(
        task_id="proof-audit",
        source=SourceRef(
            kind="fixture",
            source_id="proof-audit",
            revision="1",
            location="tests/lean/test_proof_audit.py",
            content_digest=digest_json(statement),
            attribution="AI4Algebra",
            license_ref="MIT",
        ),
        informal_statement=statement,
        family_id="audit-fixtures",
        split="test",
        imports=imports,
        universes=universes,
        binders=binders,
        lean_name="ai4algebra_audit_fixture",
        lean_statement=statement,
        mapping_evidence_id="proof-audit",
    )


def _policy(
    problem: Problem,
    *,
    allowed: tuple[str, ...] = (),
    denied: tuple[str, ...] = (),
    denied_imports: tuple[str, ...] = (),
) -> EligibilityPolicy:
    return EligibilityPolicy(
        task_id=problem.task_id,
        statement_digest=problem.statement_digest,
        allowed_imports=problem.imports,
        allowed_declarations=allowed,
        forbidden_declarations=denied,
        forbidden_imports=denied_imports,
    )


@pytest.fixture(scope="module")
def verifier() -> Verifier:
    built = subprocess.run(
        [
            "lake",
            "build",
            "AI4Algebra.Verification.Replay",
            "AI4Algebra.Verification.Audit",
            _FIXTURES,
        ],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        timeout=180,
    )
    assert built.returncode == 0, (built.stdout + built.stderr).decode(
        "utf-8", errors="replace"
    )
    return Verifier(_ROOT)


def test_scoped_multigoal_proof_is_standalone(
    verifier: Verifier, tmp_path: Path
) -> None:
    problem = _problem(
        "True ∧ (∀ a : α, a = a → a = a)", binders=("(α : Type u)",), universes=("u",)
    )
    steps = (
        Candidate(operation="constructor", goal_id="g0"),
        Candidate(operation="intro", goal_id="g1"),
        Candidate(operation="intro", goal_id="g1"),
        Candidate(operation="exact", goal_id="g1", local_id="l2"),
        Candidate(operation="constructor", goal_id="g0"),
    )
    eligibility = _policy(problem, denied=(problem.lean_name,))
    certificate = verifier.build_certificate(problem, steps, eligibility)
    verdict = verifier.verify(problem, certificate, eligibility)
    assert verdict.status == "accepted", verdict.diagnostics
    assert verdict.certificate_digest == digest_json(
        certificate.model_dump(mode="json")
    )
    assert not verdict.axioms
    assert "And.intro" in verdict.dependencies
    standalone = tmp_path / "Proof.lean"
    standalone.write_text(certificate.proof, encoding="utf-8")
    finished = subprocess.run(
        ["lake", "env", "lean", "--threads=1", str(standalone)],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        timeout=90,
    )
    assert finished.returncode == 0, (finished.stdout + finished.stderr).decode(
        "utf-8", errors="replace"
    )


def test_classical_proof_uses_only_allowed_axioms(verifier: Verifier) -> None:
    problem = _problem("p ∨ ¬ p", binders=("(p : Prop)",))
    lemma = "Classical.em"
    eligibility = _policy(problem, allowed=(lemma,))
    certificate = verifier.build_certificate(
        problem,
        (
            Candidate(
                operation="exact",
                goal_id="g0",
                lemma=lemma,
                arguments=(Argument(kind="local", reference="l0"),),
            ),
        ),
        eligibility,
    )
    verdict = verifier.verify(problem, certificate, eligibility)
    assert verdict.status == "accepted", verdict.diagnostics
    assert "Classical.choice" in verdict.axioms and set(verdict.axioms) <= set(
        AXIOM_ALLOWLIST
    )


@pytest.mark.parametrize(
    ("wrapper", "forbidden"),
    [("axiomWrapper", "newAxiom"), ("sorryWrapper", "sorryAx")],
)
def test_rejects_transitive_axiom_or_sorry(
    verifier: Verifier, wrapper: str, forbidden: str
) -> None:
    problem = _problem("True", imports=(_FIXTURES,))
    lemma = f"{_FIXTURES}.{wrapper}"
    eligibility = _policy(problem, allowed=(lemma,))
    certificate = verifier.build_certificate(
        problem, (Candidate(operation="exact", goal_id="g0", lemma=lemma),), eligibility
    )
    verdict = verifier.verify(problem, certificate, eligibility)
    assert verdict.status == "rejected", verdict.diagnostics
    assert verdict.axioms_passed is False
    assert next(name for name in verdict.axioms if name.split(".")[-1] == forbidden)


@pytest.mark.parametrize("simplification", [False, True])
def test_rejects_indirect_held_out_declaration(
    verifier: Verifier, simplification: bool
) -> None:
    if simplification:
        problem = _problem("0 + n = n", imports=(_FIXTURES,), binders=("(n : Nat)",))
        wrapper = f"{_FIXTURES}.simpWrapper"
        denied = f"{_FIXTURES}.deniedRewrite"
        action = Candidate(operation="simp_only", goal_id="g0", simp_lemmas=(wrapper,))
    else:
        problem = _problem("True", imports=(_FIXTURES,))
        wrapper = f"{_FIXTURES}.deniedWrapper"
        denied = f"{_FIXTURES}.deniedAnswer"
        action = Candidate(operation="exact", goal_id="g0", lemma=wrapper)
    eligibility = _policy(problem, allowed=(wrapper,), denied=(denied,))
    verdict = verifier.verify(
        problem,
        verifier.build_certificate(problem, (action,), eligibility),
        eligibility,
    )
    assert verdict.status == "rejected", verdict.diagnostics
    assert verdict.replay_passed is True and verdict.dependencies_passed is False
    assert wrapper in verdict.dependencies and denied in verdict.dependencies
    assert any(
        wrapper in message and denied in message for message in verdict.diagnostics
    )


def test_rejects_transitive_gold_import(verifier: Verifier) -> None:
    problem = _problem("True", imports=(_FIXTURES,))
    eligibility = _policy(
        problem, denied_imports=("AI4Algebra.Verification.GoldFixture",)
    )
    steps = (Candidate(operation="constructor", goal_id="g0"),)
    verdict = verifier.verify(
        problem, verifier.build_certificate(problem, steps, eligibility), eligibility
    )
    assert verdict.status == "rejected", verdict.diagnostics
    assert verdict.dependencies_passed is False
    assert any(
        "forbidden transitive import" in message for message in verdict.diagnostics
    )


def test_rejects_incomplete_multigoal_proof(verifier: Verifier) -> None:
    problem = _problem("True ∧ True")
    eligibility = _policy(problem)
    steps = (Candidate(operation="constructor", goal_id="g0"),) * 2
    verdict = verifier.verify(
        problem, verifier.build_certificate(problem, steps, eligibility), eligibility
    )
    assert verdict.status == "rejected", verdict.diagnostics
    assert verdict.replay_passed is False
    assert any("unsolved goals" in message for message in verdict.diagnostics)


class _SubstituteExpectedType(SubprocessWorker):
    def exchange(self, frame: bytes, timeout_seconds: float, cancelled: Event) -> bytes:
        request: dict[str, object] = json.loads(frame)
        request["expected_type"] = "False"
        substituted = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
        return super().exchange(substituted, timeout_seconds, cancelled)


def test_lean_independently_compares_the_elaborated_expected_type(
    verifier: Verifier,
) -> None:
    problem = _problem("True")
    eligibility = _policy(problem)
    steps = (Candidate(operation="constructor", goal_id="g0"),)
    certificate = verifier.build_certificate(problem, steps, eligibility)
    transport = _SubstituteExpectedType(
        (
            "lake",
            "env",
            "lean",
            "--threads=1",
            "--run",
            "AI4Algebra/Verification/Main.lean",
        ),
        _ROOT,
    )
    verdict = Verifier(_ROOT, transport=transport).verify(
        problem, certificate, eligibility
    )
    assert verdict.status == "rejected"
    assert verdict.replay_passed is True
    assert verdict.type_passed is False
    assert any("theorem type changed" in message for message in verdict.diagnostics)
