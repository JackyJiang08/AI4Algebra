"""Immutable search lineage, decision evidence, and resource accounting."""

from typing import Annotated, Literal

from pydantic import Field, model_validator
from typing_extensions import Self

from ai4algebra.config import Limits
from ai4algebra.contracts import (
    Candidate,
    CandidateSet,
    Certificate,
    Digest,
    Identifier,
    Observation,
    Problem,
    Record,
    StepResult,
    Transition,
    Verdict,
    digest_json,
)
from ai4algebra.learning import CollectedSample, EncodedDecision

SearchMode = Literal["deterministic", "best_first", "rollout"]
SearchStatus = Literal[
    "verified",
    "candidate_exhausted",
    "budget_exhausted",
    "verification_rejected",
    "infrastructure_error",
    "unsupported",
]
BudgetReason = Literal[
    "depth", "nodes", "steps", "time", "probe_limit", "step_timeout", "cancelled"
]


class SearchOptions(Record):
    probes_per_node: Annotated[int, Field(gt=0)] | None = None
    stop_on_closure: bool = False
    verification_reserve_seconds: Annotated[float, Field(gt=0)] | None = None
    continuation_reserve_seconds: Annotated[float, Field(gt=0)] | None = None
    continuation_probes: Annotated[int, Field(ge=0)] = 1
    reward_version: Literal["action-cost-v1"] = "action-cost-v1"
    action_cost: Annotated[float, Field(ge=0)] = 0.01
    verified_reward: Annotated[float, Field(gt=0)] = 1.0


class ProofNode(Record):
    node_id: Identifier
    parent_id: Identifier | None
    incoming_candidate: Candidate | None
    statement_digest: Digest
    depth: Annotated[int, Field(ge=0)]
    observation: Observation
    repeated_node_id: Identifier | None = None

    @model_validator(mode="after")
    def _validate_lineage(self) -> Self:
        root = self.depth == 0
        if root != (self.parent_id is None) or root != (
            self.incoming_candidate is None
        ):
            raise ValueError("proof node has inconsistent parent and depth")
        return self


class CandidateScore(Record):
    candidate_id: Digest
    score: float


class NodeCutoff(Record):
    node_id: Identifier
    reason: BudgetReason


class ProbeTrace(Record):
    candidate_id: Digest
    status: Identifier
    reused: bool = False
    result: StepResult | None = None


class GenerationTrace(Record):
    retrieved_premises: tuple[str, ...] = ()
    node_id: Identifier
    candidate_set: CandidateSet
    probes: tuple[ProbeTrace, ...]
    provider_status: Identifier
    provider_requests: int
    token_count_requests: int
    probe_calls: int
    recovery_calls: int = 0
    probe_limit: int | None = None
    timeout_seconds: float | None = None
    stop_on_closure: bool = False
    stopped_after_closure: bool = False
    continuation: bool = False


class Attempt(Record):
    node_id: Identifier
    collection_step: int
    candidate_set: CandidateSet
    candidate: Candidate
    encoded: EncodedDecision | None
    scores: tuple[CandidateScore, ...] = ()
    reused_probe: bool
    result: StepResult
    outcome: Identifier
    child_id: Identifier | None = None
    certificate: Certificate | None = None
    verdict: Verdict | None = None


class Work(Record):
    opens: int = 0
    nodes_expanded: int = 0
    generation_calls: int = 0
    continuation_generations: int = 0
    probe_calls: int = 0
    action_calls: int = 0
    recovery_calls: int = 0
    reused_probes: int = 0
    selected_actions: int = 0
    verifier_calls: int = 0
    provider_requests: int = 0
    token_count_requests: int = 0
    elapsed_seconds: float = 0.0

    @property
    def step_calls(self) -> int:
        return self.probe_calls + self.action_calls


class SearchReport(Record):
    problem: Problem
    policy_digest: Digest
    eligibility_digest: Digest
    policy_name: Identifier
    mode: SearchMode
    episode_id: Identifier
    limits: Limits
    options: SearchOptions
    verification_reserve_seconds: float
    continuation_reserve_seconds: float
    status: SearchStatus
    reason: Identifier
    budget_reasons: tuple[BudgetReason, ...]
    work: Work
    nodes: tuple[ProofNode, ...]
    generations: tuple[GenerationTrace, ...]
    attempts: tuple[Attempt, ...]
    last_observation: Observation | None
    final_candidate_set: CandidateSet | None
    certificate: Certificate | None = None
    verdict: Verdict | None = None
    transitions: tuple[Transition, ...] = ()
    samples: tuple[CollectedSample, ...] = ()
    diagnostics: tuple[str, ...] = ()
    last_visited_node_id: Identifier | None = None
    frontier_node_ids: tuple[Identifier, ...] | None = None
    cutoffs: tuple[NodeCutoff, ...] = ()

    @model_validator(mode="after")
    def _validate_result(self) -> Self:
        if self.status == "verified":
            if (
                self.certificate is None
                or self.verdict is None
                or self.verdict.status != "accepted"
            ):
                raise ValueError("verified report requires an accepted certificate")
            if self.verdict.certificate_digest != digest_json(
                self.certificate.model_dump(mode="json")
            ):
                raise ValueError("verdict does not identify the report certificate")
        elif self.certificate is not None or self.verdict is not None:
            raise ValueError("only verified reports may expose a selected certificate")
        if self.final_candidate_set is not None:
            if self.last_observation is None:
                raise ValueError("final candidate set lacks an observation")
            self.final_candidate_set.validate_for(self.last_observation)
        if self.transitions != tuple(
            sample.trace.transition for sample in self.samples
        ):
            raise ValueError("report transitions differ from collected samples")
        return self
