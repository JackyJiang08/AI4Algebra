"""Train from bound, verified Lean trajectory evidence."""

from ._train import TrainingOptions, TrainingPlan, TrainingReport, train

__all__ = ["TrainingOptions", "TrainingPlan", "TrainingReport", "train"]
