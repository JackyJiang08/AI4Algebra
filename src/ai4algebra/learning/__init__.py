"""Candidate-conditioned proof learning and immutable evaluation checkpoints."""

from ._collection import CollectedSample
from ._learner import CandidateDDQN, ReturnLookup
from ._records import (
    CheckpointMetadata,
    DDQNConfig,
    EncodedDecision,
    LearningSample,
    TargetBatch,
    UpdateMetrics,
    encode_decision,
)

__all__ = [
    "CandidateDDQN",
    "CheckpointMetadata",
    "CollectedSample",
    "DDQNConfig",
    "EncodedDecision",
    "LearningSample",
    "ReturnLookup",
    "TargetBatch",
    "UpdateMetrics",
    "encode_decision",
]
