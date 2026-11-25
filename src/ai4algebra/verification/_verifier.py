"""Canonical standalone proof artifacts and an independent bounded Lean verifier."""

import json
import math
import time
from pathlib import Path
from threading import Event
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import ValidationError, model_validator
from typing_extensions import Self

from ai4algebra.contracts import (
    Candidate,
    Certificate,
    Digest,
    Identifier,
    LeanName,
    NonBlank,
    Problem,
    Record,
    Verdict,
    digest_json,
)
from ai4algebra.lean_bridge import BridgeError, environment_digest
from ai4algebra.lean_bridge.protocol import (
    LEAN_VERSION,
    MATHLIB_REVISION,
    ProjectWorker,
)

from ._policy import AXIOM_ALLOWLIST, EligibilityPolicy

_REPLAY_IMPORT = "AI4Algebra.Verification.Replay"
_MAX_FRAME_BYTES = 1_048_576


class VerificationTransport(Protocol):
    def exchange(
        self, frame: bytes, timeout_seconds: float, cancelled: Event
    ) -> bytes: ...


class _AuditRequest(Record):
    request_id: Identifier
    certificate_digest: Digest
    imports: tuple[LeanName, ...]
    theorem_name: LeanName
    universes: tuple[LeanName, ...]
    expected_type: NonBlank
    declaration: NonBlank
    forbidden_declarations: tuple[LeanName, ...]
    forbidden_imports: tuple[LeanName, ...]


class _AuditResult(Record):
    replay_passed: bool
    type_passed: bool | None
    axioms_passed: bool | None
    dependencies_passed: bool | None
    axioms: tuple[NonBlank, ...]
    dependencies: tuple[NonBlank, ...]
    diagnostics: tuple[NonBlank, ...]

    @model_validator(mode="after")
    def _check_result(self) -> Self:
        if self.replay_passed and (
            self.type_passed is None or self.axioms_passed is None
        ):
            raise ValueError("successful replay requires type and axiom outcomes")
        if self.axioms_passed is True and set(self.axioms) - set(AXIOM_ALLOWLIST):
            raise ValueError("Lean declared an unapproved axiom admissible")
        if len(set(self.axioms)) != len(self.axioms) or len(
            set(self.dependencies)
        ) != len(self.dependencies):
            raise ValueError("Lean audit contains duplicate declaration names")
        return self


class _AuditResponse(Record):
    request_id: Identifier
    certificate_digest: Digest
    lean_version: NonBlank
    result: _AuditResult | None = None
    error: NonBlank | None = None

    @model_validator(mode="after")
    def _check_result(self) -> Self:
        if (self.result is None) == (self.error is None):
            raise ValueError("Lean audit response requires exactly one result or error")
        return self


def _action_line(action: Candidate) -> str:
    fields = action.model_dump(
        mode="json",
        exclude={"schema_version", "candidate_id", "provenance", "generator_version"},
    )
    payload = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
    return "  ai4algebra_step " + json.dumps(payload, ensure_ascii=False)


def _declaration(problem: Problem, steps: tuple[Candidate, ...]) -> str:
    universes = ".{" + ", ".join(problem.universes) + "}" if problem.universes else ""
    binders = "".join(f" {binder}" for binder in problem.binders)
    header = f"theorem {problem.lean_name}{universes}{binders} : ({problem.lean_statement}) := by"
    body = tuple(map(_action_line, steps)) if steps else ("  skip",)
    return "\n".join((header, *body, ""))


def render_proof(problem: Problem, steps: tuple[Candidate, ...]) -> str:
    """Render the theorem from the trusted header and typed operations."""
    imports = "\n".join(
        f"import {module}" for module in (_REPLAY_IMPORT, *problem.imports)
    )
    return (
        f"{imports}\n\nset_option autoImplicit false\n\n{_declaration(problem, steps)}"
    )


def _expected_type(problem: Problem) -> str:
    statement = f"({problem.lean_statement})"
    if not problem.binders:
        return statement
    return f"∀ {' '.join(problem.binders)}, {statement}"


class Verifier:
    """Compile and audit a fresh theorem independently of bridge observations."""

    def __init__(
        self,
        project_root: Path,
        *,
        timeout_seconds: float = 90.0,
        transport: VerificationTransport | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("verifier timeout must be finite and positive")
        self._root = project_root.resolve()
        self._timeout_seconds = timeout_seconds
        self._transport = (
            transport
            if transport is not None
            else ProjectWorker(self._root, "verifier")
        )

    def build_certificate(
        self,
        problem: Problem,
        steps: tuple[Candidate, ...],
        eligibility: EligibilityPolicy,
    ) -> Certificate:
        eligibility.validate_for(problem, steps)
        return Certificate(
            task_id=problem.task_id,
            statement_digest=problem.statement_digest,
            environment_digest=environment_digest(self._root, problem.imports),
            source_digest=problem.source.content_digest,
            policy_digest=eligibility.policy_digest,
            eligibility_digest=eligibility.eligibility_digest,
            imports=problem.imports,
            steps=steps,
            proof=render_proof(problem, steps),
        )

    def verify(
        self,
        problem: Problem,
        certificate: Certificate,
        eligibility: EligibilityPolicy,
        *,
        timeout_seconds: float | None = None,
        cancelled: Event | None = None,
    ) -> Verdict:
        if timeout_seconds is not None and not math.isfinite(timeout_seconds):
            raise ValueError("verification timeout must be finite")
        timeout = (
            self._timeout_seconds
            if timeout_seconds is None
            else min(self._timeout_seconds, timeout_seconds)
        )
        deadline = time.monotonic() + timeout
        certificate_digest = digest_json(certificate.model_dump(mode="json"))
        signal = Event() if cancelled is None else cancelled
        if signal.is_set():
            return self._failure(
                certificate_digest, "indeterminate", "verification cancelled"
            )
        if timeout <= 0:
            return self._failure(
                certificate_digest, "indeterminate", "verification deadline expired"
            )
        try:
            problem = Problem.from_json(problem.to_json())
            certificate = Certificate.from_json(certificate.to_json())
            eligibility = EligibilityPolicy.from_json(eligibility.to_json())
            expected = self.build_certificate(problem, certificate.steps, eligibility)
        except (ValidationError, ValueError) as exc:
            return self._failure(certificate_digest, "rejected", str(exc))
        except BridgeError as exc:
            return self._failure(certificate_digest, "indeterminate", str(exc))
        metadata = (
            "task_id",
            "statement_digest",
            "environment_digest",
            "source_digest",
            "policy_digest",
            "eligibility_digest",
            "imports",
            "proof",
            "proof_digest",
        )
        for attribute in metadata:
            if getattr(expected, attribute) != getattr(certificate, attribute):
                return self._failure(
                    certificate_digest,
                    "rejected",
                    f"certificate {attribute} differs from the trusted reconstruction",
                )

        request = _AuditRequest(
            request_id=uuid4().hex,
            certificate_digest=certificate_digest,
            imports=problem.imports,
            theorem_name=problem.lean_name,
            universes=problem.universes,
            expected_type=_expected_type(problem),
            declaration=_declaration(problem, certificate.steps),
            forbidden_declarations=eligibility.forbidden_declarations,
            forbidden_imports=eligibility.forbidden_imports,
        )
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeError("verification deadline expired")
            if signal.is_set():
                raise BridgeError("verification cancelled")
            outcome = self._audit(request, remaining, signal)
            if signal.is_set():
                raise BridgeError("verification cancelled")
        except BridgeError as exc:
            return self._failure(certificate_digest, "indeterminate", str(exc))

        checks = (
            outcome.replay_passed,
            outcome.type_passed,
            outcome.axioms_passed,
            outcome.dependencies_passed,
        )
        status: Literal["accepted", "rejected", "indeterminate"] = (
            "rejected"
            if False in checks
            else "indeterminate"
            if None in checks
            else "accepted"
        )
        return Verdict(
            status=status,
            replay_passed=outcome.replay_passed,
            type_passed=outcome.type_passed,
            axioms_passed=outcome.axioms_passed,
            dependencies_passed=outcome.dependencies_passed,
            lean_version=LEAN_VERSION,
            mathlib_revision=MATHLIB_REVISION,
            certificate_digest=certificate_digest,
            axioms=outcome.axioms,
            dependencies=outcome.dependencies,
            diagnostics=outcome.diagnostics,
        )

    def _audit(
        self, request: _AuditRequest, timeout_seconds: float, cancelled: Event
    ) -> _AuditResult:
        frame = (request.to_json() + "\n").encode("utf-8")
        if len(frame) > _MAX_FRAME_BYTES:
            raise BridgeError("Lean audit request exceeds its byte limit")
        output = self._transport.exchange(frame, timeout_seconds, cancelled)
        try:
            data = output.decode("utf-8", errors="strict")
            if not data.endswith("\n") or data.count("\n") != 1:
                raise ValueError("expected a single complete frame")
            response = _AuditResponse.from_json(data)
        except (ValidationError, ValueError) as exc:
            raise BridgeError("Lean verifier returned an invalid JSON frame") from exc
        if (response.request_id, response.certificate_digest) != (
            request.request_id,
            request.certificate_digest,
        ):
            raise BridgeError(
                "Lean verifier response identity does not match the request"
            )
        if response.lean_version != LEAN_VERSION:
            raise BridgeError("Lean verifier toolchain does not match the project pin")
        if response.result is None:
            raise BridgeError(response.error or "Lean verifier infrastructure failure")
        return response.result

    @staticmethod
    def _failure(
        certificate_digest: str,
        status: Literal["rejected", "indeterminate"],
        diagnostic: str,
    ) -> Verdict:
        return Verdict(
            status=status,
            replay_passed=None,
            type_passed=None,
            axioms_passed=None,
            dependencies_passed=None,
            lean_version=LEAN_VERSION,
            mathlib_revision=MATHLIB_REVISION,
            certificate_digest=certificate_digest,
            diagnostics=(diagnostic,),
        )
