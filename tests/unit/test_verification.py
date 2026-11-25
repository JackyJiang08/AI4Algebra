"""Check certificate identity and the verifier protocol independently of Lean startup."""

import json
from collections.abc import Callable
from pathlib import Path
from threading import Event

import pytest
from pydantic import ValidationError

from ai4algebra.contracts import Candidate, Certificate, Problem, SourceRef, digest_json
from ai4algebra.lean_bridge import BridgeError, BridgeTimeout
from ai4algebra.verification import EligibilityPolicy, Verifier, render_proof

_ROOT = Path(__file__).resolve().parents[2]
_ACTION = Candidate(operation="constructor", goal_id="g0")


def _problem(
    statement: str = "True",
    *,
    imports: tuple[str, ...] = (),
    binders: tuple[str, ...] = (),
) -> Problem:
    return Problem(
        task_id="verify-fixture",
        source=SourceRef(
            kind="fixture",
            source_id="verify-fixture",
            revision="1",
            location="tests/unit/test_verification.py",
            content_digest=digest_json(statement),
            attribution="AI4Algebra",
            license_ref="MIT",
        ),
        informal_statement=statement,
        family_id="verification-fixtures",
        split="test",
        imports=imports,
        binders=binders,
        lean_name="verifier_fixture",
        lean_statement=statement,
        mapping_evidence_id="verification-fixture",
    )


def _policy(problem: Problem, **fields: object) -> EligibilityPolicy:
    policy: dict[str, object] = {
        "task_id": problem.task_id,
        "statement_digest": problem.statement_digest,
        "allowed_imports": problem.imports,
    }
    return EligibilityPolicy.model_validate(policy | fields)


class _Transport:
    def __init__(
        self,
        *,
        response_updates: dict[str, object] | None = None,
        result_updates: dict[str, object] | None = None,
        failure: BridgeError | None = None,
    ) -> None:
        self.requests: list[dict[str, object]] = []
        self.timeouts: list[float] = []
        self.response_updates = response_updates or {}
        self.result_updates = result_updates or {}
        self.failure = failure

    def exchange(self, frame: bytes, timeout_seconds: float, cancelled: Event) -> bytes:
        assert timeout_seconds > 0 and not cancelled.is_set()
        self.timeouts.append(timeout_seconds)
        request: dict[str, object] = json.loads(frame)
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        result: dict[str, object] = {
            "schema_version": 1,
            "replay_passed": True,
            "type_passed": True,
            "axioms_passed": True,
            "dependencies_passed": True,
            "axioms": [],
            "dependencies": ["True", "True.intro"],
            "diagnostics": [],
        }
        response = {
            "schema_version": 1,
            "request_id": request["request_id"],
            "certificate_digest": request["certificate_digest"],
            "lean_version": "4.34.0-rc1",
            "result": result | self.result_updates,
        }
        return (json.dumps(response | self.response_updates) + "\n").encode("utf-8")


def test_certificate_binds_original_problem_and_both_policy_digests() -> None:
    problem = _problem(imports=("Mathlib.Algebra.Group.Defs",), binders=("(h : True)",))
    policy = _policy(problem, bundle_digest=digest_json("task-policy-catalog"))
    worker = _Transport()
    verifier = Verifier(_ROOT, transport=worker)
    steps = (Candidate(operation="exact", goal_id="g0", local_id="l0"),)
    certificate = verifier.build_certificate(problem, steps, policy)
    verdict = verifier.verify(problem, certificate, policy)
    assert certificate.proof == render_proof(problem, steps)
    assert f"import {problem.imports[0]}" in certificate.proof
    assert "theorem verifier_fixture (h : True) : (True) := by" in certificate.proof
    assert certificate.eligibility_digest == policy.eligibility_digest
    assert (
        certificate.policy_digest == policy.bundle_digest != policy.eligibility_digest
    )
    assert certificate.source_digest == problem.source.content_digest
    assert verdict.status == "accepted"
    assert verdict.certificate_digest == digest_json(
        certificate.model_dump(mode="json")
    )
    assert worker.requests[0]["expected_type"] == "∀ (h : True), (True)"


@pytest.mark.parametrize(
    "proof_change",
    [
        lambda proof: proof.replace("(h : True)", "(h : False)"),
        lambda proof: proof.replace(": (True) := by", ": (False) := by"),
        lambda proof: proof.split("  ai4algebra_step")[0] + "  sorry\n",
        lambda proof: proof.split("  ai4algebra_step")[0] + "  admit\n",
        lambda proof: proof + "\naxiom injected : False\n",
        lambda proof: "import Unexpected.Gold\n" + proof,
    ],
)
def test_rejects_changed_script_even_with_recomputed_digest(
    proof_change: Callable[[str], str],
) -> None:
    problem = _problem(binders=("(h : True)",))
    policy = _policy(problem)
    worker = _Transport()
    verifier = Verifier(_ROOT, transport=worker)
    certificate = verifier.build_certificate(problem, (_ACTION,), policy)
    payload = certificate.model_dump(exclude={"proof_digest"})
    payload["proof"] = proof_change(certificate.proof)
    modified = Certificate.model_validate(payload)
    assert modified.proof_digest != certificate.proof_digest
    verdict = verifier.verify(problem, modified, policy)
    assert verdict.status == "rejected"
    assert verdict.certificate_digest == digest_json(modified.model_dump(mode="json"))
    assert "reconstruction" in verdict.diagnostics[0]
    assert not worker.requests


@pytest.mark.parametrize(
    "field",
    [
        "environment_digest",
        "eligibility_digest",
        "statement_digest",
        "policy_digest",
        "source_digest",
    ],
)
def test_rejects_stale_certificate_metadata(field: str) -> None:
    problem = _problem()
    policy = _policy(problem)
    worker = _Transport()
    verifier = Verifier(_ROOT, transport=worker)
    certificate = verifier.build_certificate(problem, (_ACTION,), policy)
    changed = certificate.model_copy(update={field: digest_json(field)})
    verdict = verifier.verify(problem, changed, policy)
    assert verdict.status == "rejected"
    assert field in verdict.diagnostics[0]
    assert not worker.requests


def test_policy_rejects_action_alias_self_reference_and_import_changes() -> None:
    problem = _problem(imports=("Mathlib",))
    worker = _Transport()
    verifier = Verifier(_ROOT, transport=worker)
    exact_self = Candidate(operation="exact", goal_id="g0", lemma=problem.lean_name)
    with pytest.raises(ValueError, match="ineligible action"):
        verifier.build_certificate(
            problem,
            (exact_self,),
            _policy(problem, allowed_declarations=(problem.lean_name,)),
        )
    with pytest.raises(ValueError, match="eligibility policy"):
        verifier.build_certificate(
            problem, (_ACTION,), _policy(problem, allowed_imports=())
        )
    with pytest.raises(ValueError, match="forbidden import"):
        verifier.build_certificate(
            problem, (_ACTION,), _policy(problem, forbidden_imports=("Mathlib",))
        )
    denied = Candidate(operation="simp_only", goal_id="g0", simp_lemmas=("Eq.refl",))
    with pytest.raises(ValueError, match="ineligible action"):
        verifier.build_certificate(problem, (denied,), _policy(problem))
    assert not worker.requests


def test_rejects_a_trusted_record_with_inconsistent_statement_hash() -> None:
    problem = _problem()
    policy = _policy(problem)
    worker = _Transport()
    verifier = Verifier(_ROOT, transport=worker)
    certificate = verifier.build_certificate(problem, (_ACTION,), policy)
    stale_problem = problem.model_copy(update={"lean_statement": "False"})
    verdict = verifier.verify(stale_problem, certificate, policy)
    assert verdict.status == "rejected"
    assert "statement_digest" in verdict.diagnostics[0]
    assert not worker.requests


def test_eligibility_digest_is_independent_of_set_order_and_validates_round_trip() -> (
    None
):
    problem = _problem()
    left = _policy(problem, allowed_declarations=("True.intro", "And.intro"))
    right = _policy(problem, allowed_declarations=("And.intro", "True.intro"))
    assert left.eligibility_digest == right.eligibility_digest
    assert EligibilityPolicy.from_json(left.to_json()) == left
    with pytest.raises(ValidationError, match="eligibility digest"):
        _policy(problem, eligibility_digest=digest_json("stale"))
    with pytest.raises(ValidationError, match="overlap"):
        _policy(
            problem,
            allowed_declarations=("True.intro",),
            forbidden_declarations=("True.intro",),
        )


@pytest.mark.parametrize(
    "worker",
    [
        _Transport(failure=BridgeError("worker crash")),
        _Transport(failure=BridgeTimeout("worker deadline expired")),
        _Transport(response_updates={"lean_version": "4.35.0"}),
        _Transport(response_updates={"request_id": "wrong-request"}),
        _Transport(response_updates={"result": None, "error": "missing import"}),
        _Transport(result_updates={"dependencies_passed": None}),
        _Transport(result_updates={"axioms": ["extraAxiom"]}),
    ],
)
def test_unknown_or_inconsistent_audit_is_indeterminate(worker: _Transport) -> None:
    problem = _problem()
    policy = _policy(problem)
    verifier = Verifier(_ROOT, transport=worker)
    certificate = verifier.build_certificate(problem, (_ACTION,), policy)
    verdict = verifier.verify(problem, certificate, policy)
    assert verdict.status == "indeterminate"
    assert verdict.certificate_digest == digest_json(
        certificate.model_dump(mode="json")
    )
    assert verdict.dependencies_passed is None


def test_per_call_timeout_respects_configured_cap_and_skips_expired_work() -> None:
    problem = _problem()
    policy = _policy(problem)
    worker = _Transport()
    verifier = Verifier(_ROOT, transport=worker, timeout_seconds=4.0)
    certificate = verifier.build_certificate(problem, (_ACTION,), policy)
    assert (
        verifier.verify(problem, certificate, policy, timeout_seconds=8.0).status
        == "accepted"
    )
    assert (
        verifier.verify(problem, certificate, policy, timeout_seconds=1.25).status
        == "accepted"
    )
    expired = verifier.verify(problem, certificate, policy, timeout_seconds=0.0)
    assert expired.status == "indeterminate"
    assert expired.diagnostics == ("verification deadline expired",)
    with pytest.raises(ValueError, match="finite"):
        verifier.verify(problem, certificate, policy, timeout_seconds=float("nan"))
    assert len(worker.timeouts) == 2
    assert 0 < worker.timeouts[0] <= 4.0
    assert 0 < worker.timeouts[1] <= 1.25
