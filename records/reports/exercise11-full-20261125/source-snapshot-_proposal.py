"""Bounded typed tactic proposals and the offline deterministic provider."""

import json
from dataclasses import dataclass
from itertools import zip_longest
from threading import Event
from typing import Literal, Protocol

from ai4algebra.config import Limits
from ai4algebra.contracts import Candidate, Goal, LeanName, NonBlank, Record

from ._rules import (
    GENERATOR_VERSION,
    MAX_OPERANDS,
    LemmaRule,
    _CandidateFlags,
    _instantiate,
    _shape,
)

ProviderStatus = Literal[
    "not_requested",
    "ok",
    "disabled",
    "budget_exhausted",
    "input_limit",
    "malformed",
    "refused",
    "incomplete",
    "timeout",
    "cancelled",
    "unavailable",
    "pricing_mismatch",
]


class ProposalRequest(Record):
    """The public statement, current goals, and reviewed signatures visible to a proposer."""

    statement: NonBlank
    binders: tuple[NonBlank, ...] = ()
    universes: tuple[LeanName, ...] = ()
    goals: tuple[Goal, ...]
    premises: tuple[LemmaRule, ...]

    def prompt_data(self) -> dict[str, object]:
        return {
            "statement": self.statement,
            "binders": self.binders,
            "universes": self.universes,
            "goals": [
                {
                    "goal_id": goal.goal_id,
                    "target": goal.target,
                    "hypotheses": [
                        {
                            "local_id": hyp.local_id,
                            "binder_kind": hyp.binder_kind,
                            "name": hyp.name,
                            "type": hyp.type_text,
                        }
                        for hyp in goal.hypotheses
                    ],
                }
                for goal in self.goals
            ],
            "premises": [
                # Only the structural type is validated and dependency-filtered.
                # A separate display string is not evidence of a safe signature.
                {"name": rule.name, "type_expression": json.loads(rule.expression)}
                for rule in self.premises
            ],
        }


@dataclass(frozen=True)
class ProposalResult:
    status: ProviderStatus
    candidates: tuple[Candidate, ...] = ()
    requests: int = 0
    token_count_requests: int = 0


class TacticProposer(Protocol):
    def propose(
        self,
        request: ProposalRequest,
        limits: Limits,
        *,
        timeout_seconds: float | None = None,
        cancelled: Event | None = None,
    ) -> ProposalResult: ...


class DeterministicProposer:
    def __init__(self, *, computational: bool = False) -> None:
        self._computational = computational

    def propose(
        self,
        request: ProposalRequest,
        limits: Limits,
        *,
        timeout_seconds: float | None = None,
        cancelled: Event | None = None,
    ) -> ProposalResult:
        if cancelled is not None and cancelled.is_set():
            return ProposalResult("cancelled")
        by_goal = [
            self._for_goal(goal, request.premises, computational=self._computational)
            for goal in request.goals[: limits.max_candidates]
        ]
        # Interleave focus positions while preserving each goal's template priority.
        candidates = tuple(
            candidate
            for row in zip_longest(*by_goal)
            for candidate in row
            if candidate is not None
        )
        return ProposalResult("ok", candidates[: limits.max_candidates])

    @staticmethod
    def _for_goal(
        goal: Goal, rules: tuple[LemmaRule, ...], *, computational: bool = False
    ) -> tuple[Candidate, ...]:
        flags: _CandidateFlags = {
            "goal_id": goal.goal_id,
            "generator_version": GENERATOR_VERSION,
        }
        term = json.loads(goal.expression)
        shape = _shape(term)
        direct = []
        if isinstance(term, list) and term and term[0] == "forall":
            direct.append(Candidate(operation="intro", **flags))
        if shape[:2] in (("const", "And"), ("const", "True"), ("const", "Iff")):
            direct.append(Candidate(operation="constructor", **flags))
        for hyp in goal.hypotheses:
            if _shape(json.loads(hyp.expression)) == shape:
                direct.append(
                    Candidate(operation="exact", local_id=hyp.local_id, **flags)
                )
                break
        if (
            shape[:2] == ("const", "Eq")
            and len(shape[2]) == 2
            and shape[2][0] == shape[2][1]
        ):
            direct.append(Candidate(operation="reflexivity", **flags))
        groups = tuple(_instantiate(rule, goal) for rule in rules)
        typed = tuple(candidate for matched, _ in groups for candidate in matched)
        guesses = sorted(
            (candidate for _, inferred in groups for candidate in inferred),
            key=lambda candidate: (
                candidate.direction == "backward",
                candidate.operation != "rewrite",
            ),
        )[:MAX_OPERANDS]
        rewrites = tuple(
            dict.fromkeys(
                candidate.lemma
                for candidate in typed
                if candidate.operation == "rewrite"
                and candidate.direction == "forward"
                and candidate.lemma is not None
            )
        )
        exact = tuple(
            candidate for candidate in typed if candidate.operation == "exact"
        )
        simplifiers = (
            ()
            if not rewrites
            else (
                Candidate(
                    operation="simp_only", simp_lemmas=rewrites[:MAX_OPERANDS], **flags
                ),
            )
        )
        apply_or_rewrite = tuple(
            candidate
            for candidate in typed
            if candidate.operation != "exact" and candidate.direction == "forward"
        )
        forward_guesses = tuple(
            candidate for candidate in guesses if candidate.direction == "forward"
        )
        reverse_rewrites = tuple(
            candidate
            for candidate in (*typed, *guesses)
            if candidate.direction == "backward"
        )
        fallback = (
            Candidate(operation="assumption", **flags),
            Candidate(operation="reflexivity", **flags),
        )
        # Conditional rewrites can need another retrieved lemma to discharge their
        # premises. Keep the complete bounded bundle as a separate, probed action.
        bundle = (
            (
                Candidate(
                    operation="simp_only",
                    simp_lemmas=tuple(rule.name for rule in rules[:MAX_OPERANDS]),
                    **flags,
                ),
            )
            if rules and computational
            else ()
        )
        return tuple(
            # Keep reverse rewrites available after forward transformations so
            # a rollout does not immediately undo a useful forward rewrite.
            dict.fromkeys(
                (
                    *direct,
                    *exact,
                    *bundle,
                    *(
                        (Candidate(operation="decide", **flags),)
                        if computational
                        else ()
                    ),
                    *simplifiers,
                    *apply_or_rewrite,
                    *forward_guesses,
                    *reverse_rewrites,
                    *fallback,
                )
            )
        )
