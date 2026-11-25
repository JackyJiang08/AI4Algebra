"""Action selection over the exact candidates visible to search."""

from dataclasses import dataclass
from typing import Protocol

from numpy.random import Generator

from ai4algebra.contracts import CandidateSet, Observation
from ai4algebra.learning import CandidateDDQN, EncodedDecision, ReturnLookup

from ._records import CandidateScore


@dataclass(frozen=True)
class Decision:
    observation: Observation
    candidate_set: CandidateSet
    encoded: EncodedDecision | None
    episode_id: str
    collection_step: int


@dataclass(frozen=True)
class Choice:
    candidate_id: str
    scores: tuple[CandidateScore, ...] = ()


class ActionPolicy(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def requires_encoding(self) -> bool: ...

    def choose(self, decision: Decision) -> Choice: ...


class DeterministicPolicy:
    """Select the first eligible candidate in the generator's stable order."""

    name = "deterministic"
    requires_encoding = False

    def choose(self, decision: Decision) -> Choice:
        for candidate, eligible in zip(
            decision.candidate_set.candidates,
            decision.candidate_set.eligible,
            strict=True,
        ):
            if eligible:
                return Choice(candidate.candidate_id)
        raise ValueError("deterministic policy requires an eligible candidate")


class DDQNPolicy:
    """Apply candidate-conditioned scores and optional causal return retrieval."""

    requires_encoding = True

    def __init__(
        self,
        learner: CandidateDDQN,
        *,
        epsilon: float = 0.0,
        rng: Generator | None = None,
        memory: ReturnLookup | None = None,
        retrieval_weight: float = 0.0,
        before_step: int | None = None,
    ) -> None:
        if not 0.0 <= epsilon <= 1.0 or (epsilon > 0.0 and rng is None):
            raise ValueError(
                "epsilon must be within [0, 1] and exploration requires an RNG"
            )
        if not 0.0 <= retrieval_weight <= 1.0 or (
            retrieval_weight > 0 and memory is None
        ):
            raise ValueError(
                "retrieval weight must be within [0, 1] and blending requires memory"
            )
        self.name = "ddqn_retrieval" if retrieval_weight else "ddqn"
        self._learner = learner
        self._epsilon = epsilon
        self._rng = rng
        self._memory = memory
        self._weight = retrieval_weight
        self._before_step = before_step

    def choose(self, decision: Decision) -> Choice:
        if decision.encoded is None:
            raise ValueError("DDQN policy requires stored decision features")
        scores = self._learner.behavior_scores(
            decision.encoded,
            memory=self._memory,
            retrieval_weight=self._weight,
            before_step=(
                decision.collection_step
                if self._before_step is None
                else self._before_step
            ),
            exclude_episode=decision.episode_id,
        )
        if not scores:
            raise ValueError("DDQN policy requires an eligible candidate")
        ordered = sorted(scores)
        rng = self._rng
        if rng is not None and self._epsilon > 0.0 and rng.random() < self._epsilon:
            selected = ordered[int(rng.integers(len(ordered)))]
        else:
            selected = min(ordered, key=lambda key: (-scores[key], key))
        return Choice(
            selected,
            tuple(
                CandidateScore(candidate_id=key, score=scores[key]) for key in ordered
            ),
        )
