"""Kernel decide and retrieved conditional simplification survive independent replay."""

from pathlib import Path

import pytest

from ai4algebra.config import Limits
from ai4algebra.contracts import Candidate
from ai4algebra.lean_bridge import LeanBridge
from ai4algebra.selected_full import problems_and_policies
from ai4algebra.verification import Verifier

pytestmark = pytest.mark.lean


@pytest.mark.parametrize("task_index", [0, 1])
def test_computational_actions_replay_without_native_axioms(task_index: int) -> None:
    root = Path(__file__).resolve().parents[2]
    tasks, policies = problems_and_policies(root)
    problem, policy = tasks[task_index], policies[task_index]
    bridge = LeanBridge(root)
    snapshot, _ = bridge.open(
        problem, Limits(step_timeout_seconds=120.0, task_timeout_seconds=480.0)
    )
    steps = (
        Candidate(
            operation="simp_only", goal_id="g0", simp_lemmas=policy.allowed_declarations
        ),
        Candidate(operation="decide", goal_id="g0"),
    )
    try:
        first = bridge.step(snapshot, steps[0])
        assert first.status == "advanced", first.diagnostics
        assert first.snapshot is not None
        final = bridge.step(first.snapshot, steps[1])
        assert final.status == "closed", final.diagnostics
    finally:
        bridge.close(snapshot.session_id)
    verifier = Verifier(root, timeout_seconds=120.0)
    certificate = verifier.build_certificate(problem, steps, policy)
    verdict = verifier.verify(problem, certificate, policy)
    assert verdict.status == "accepted", verdict
    assert set(verdict.axioms) <= {"propext", "Classical.choice", "Quot.sound"}
