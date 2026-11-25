"""Typed tactic generation, Lean applicability and optional bounded proposals."""

from ._budget import ASTRA_STANDARD, BudgetError, BudgetLedger, BudgetSummary
from ._elementary import elementary_premise_index
from ._generator import CandidateGenerator, CandidateProbe, GenerationResult
from ._http import Endpoint, HttpResponse, ResponsesTransport, TransportError
from ._openai import OpenAIProposer
from ._proposal import (
    DeterministicProposer,
    ProposalRequest,
    ProposalResult,
    TacticProposer,
)
from ._rules import GENERATOR_VERSION, LemmaRule, PremiseIndex, instantiate

__all__ = [
    "ASTRA_STANDARD",
    "GENERATOR_VERSION",
    "BudgetError",
    "BudgetLedger",
    "BudgetSummary",
    "CandidateGenerator",
    "CandidateProbe",
    "DeterministicProposer",
    "Endpoint",
    "GenerationResult",
    "HttpResponse",
    "LemmaRule",
    "OpenAIProposer",
    "PremiseIndex",
    "ProposalRequest",
    "ProposalResult",
    "ResponsesTransport",
    "TacticProposer",
    "TransportError",
    "elementary_premise_index",
    "instantiate",
]
