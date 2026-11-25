"""Immutable task declaration and import eligibility for independent replay."""

from pydantic import Field, model_validator
from typing_extensions import Self

from ai4algebra.contracts import (
    Candidate,
    Digest,
    Identifier,
    LeanName,
    Problem,
    Record,
    digest_json,
)

AXIOM_ALLOWLIST = ("Classical.choice", "Quot.sound", "propext")
_VERIFIER_VERSION = "lean-verifier-v1"
_COMPUTED_DIGEST = "Computed from the immutable record contents."


class EligibilityPolicy(Record):
    task_id: Identifier
    statement_digest: Digest
    allowed_imports: tuple[LeanName, ...]
    allowed_declarations: tuple[LeanName, ...] = ()
    forbidden_declarations: tuple[LeanName, ...] = ()
    forbidden_imports: tuple[LeanName, ...] = ()
    bundle_digest: Digest | None = None
    eligibility_digest: Digest = Field(
        default="", validate_default=False, description=_COMPUTED_DIGEST
    )
    policy_digest: Digest = Field(
        default="", validate_default=False, description=_COMPUTED_DIGEST
    )

    @model_validator(mode="after")
    def _validate_policy(self) -> Self:
        for names in (
            self.allowed_imports,
            self.allowed_declarations,
            self.forbidden_declarations,
            self.forbidden_imports,
        ):
            if len(set(names)) != len(names):
                raise ValueError("duplicate name in eligibility policy")
        if set(self.allowed_declarations) & set(self.forbidden_declarations):
            raise ValueError("allowed and forbidden declarations overlap")
        calculated = digest_json(
            (
                self.schema_version,
                _VERIFIER_VERSION,
                AXIOM_ALLOWLIST,
                self.task_id,
                self.statement_digest,
                self.allowed_imports,
                sorted(self.allowed_declarations),
                sorted(self.forbidden_declarations),
                sorted(self.forbidden_imports),
            )
        )
        if self.eligibility_digest and self.eligibility_digest != calculated:
            raise ValueError("eligibility digest does not match its contents")
        policy_digest = self.bundle_digest or calculated
        if self.policy_digest and self.policy_digest != policy_digest:
            raise ValueError("policy digest does not match its contents")
        object.__setattr__(self, "eligibility_digest", calculated)
        object.__setattr__(self, "policy_digest", policy_digest)
        return self

    def validate_for(self, problem: Problem, steps: tuple[Candidate, ...]) -> None:
        if (self.task_id, self.statement_digest) != (
            problem.task_id,
            problem.statement_digest,
        ):
            raise ValueError(
                "the eligibility policy belongs to a different task or statement"
            )
        if problem.imports != self.allowed_imports:
            raise ValueError("the trusted imports differ from the eligibility policy")
        for module in problem.imports:
            if any(
                module == banned or module.startswith(f"{banned}.")
                for banned in self.forbidden_imports
            ):
                raise ValueError(f"forbidden import {module}")

        allowed = set(self.allowed_declarations)
        forbidden = {*self.forbidden_declarations, problem.lean_name, "sorryAx"}
        for step in steps:
            declarations = {
                arg.reference for arg in step.arguments if arg.kind == "lemma"
            }
            if step.lemma is not None:
                declarations.add(step.lemma)
            declarations.update(step.simp_lemmas)
            denied = declarations - allowed | declarations & forbidden
            if denied:
                raise ValueError(f"ineligible action declaration {min(denied)}")
