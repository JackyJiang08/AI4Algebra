"""Exercise the real Windows/Linux pinned Lean observer."""

import json
import os
import subprocess
from pathlib import Path
from threading import Event

import pytest

from ai4algebra.config import Limits
from ai4algebra.contracts import (
    Argument,
    Candidate,
    Operation,
    Problem,
    SourceRef,
    digest_json,
)
from ai4algebra.lean_bridge import BridgeError, LeanBridge, StepUsage
from ai4algebra.lean_bridge.protocol import (
    SubprocessWorker,
    WorkerRequest,
    WorkerResult,
)

pytestmark = pytest.mark.lean
_ROOT = Path(__file__).resolve().parents[2]
_LIMITS = Limits(step_timeout_seconds=90.0, task_timeout_seconds=450.0)


def _problem(statement: str, **header: object) -> Problem:
    fields: dict[str, object] = {
        "task_id": "bridge-fixture",
        "source": SourceRef(
            kind="fixture",
            source_id="bridge-fixture",
            revision="1",
            location="tests/lean/test_bridge.py",
            content_digest=digest_json(statement),
            attribution="AI4Algebra",
            license_ref="MIT",
        ),
        "informal_statement": statement,
        "family_id": "bridge-fixtures",
        "split": "train",
        "imports": (),
        "lean_name": "ai4algebra_bridge_fixture",
        "lean_statement": statement,
        "mapping_evidence_id": "bridge-fixture",
    }
    return Problem.model_validate(fields | header)


def test_pinned_mathlib_json_spike() -> None:
    bridge = LeanBridge(_ROOT)
    problem = _problem(
        "x * 1 = x",
        imports=("Mathlib.Algebra.Group.Defs",),
        universes=("u",),
        binders=("(G : Type u)", "[Group G]", "(x : G)"),
    )
    root, observation = bridge.open(problem, _LIMITS)
    try:
        (goal,) = observation.goals
        assert goal.target == "x * 1 = x"
        assert json.loads(goal.expression)[0] == "app"
        assert [hyp.type_text for hyp in goal.hypotheses] == ["Type u", "Group G", "G"]
        assert [hyp.local_id for hyp in goal.hypotheses] == ["l0", "l1", "l2"]
        rejected = bridge.step(
            root, Candidate(operation="assumption", goal_id=goal.goal_id)
        )
        assert rejected.status == "rejected", rejected.diagnostics
        assert rejected.observation == observation
        assert "assumption" in rejected.diagnostics[0]
        closed = bridge.step(
            bridge.fork(root),
            Candidate(
                operation="exact",
                goal_id=goal.goal_id,
                lemma="mul_one",
                arguments=(Argument(kind="local", reference="l2"),),
            ),
        )
        assert closed.status == "closed", closed.diagnostics
        assert closed.snapshot != root
        assert closed.observation is not None and closed.observation.goals == ()
    finally:
        bridge.close(root.session_id)
    with pytest.raises(BridgeError, match="closed"):
        bridge.observe(root)


def test_focused_branch_preserves_all_other_goals() -> None:
    bridge = LeanBridge(_ROOT)
    root, initial = bridge.open(_problem("True ∧ (1 = 1 ∧ True)"), _LIMITS)
    try:
        first = bridge.step(root, Candidate(operation="constructor", goal_id="g0"))
        assert first.status == "advanced", first.diagnostics
        assert first.snapshot is not None and first.observation is not None
        before = first.snapshot
        assert tuple(goal.target for goal in first.observation.goals) == (
            "True",
            "1 = 1 ∧ True",
        )
        right = bridge.step(
            bridge.fork(before), Candidate(operation="constructor", goal_id="g1")
        )
        assert right.status == "advanced", right.diagnostics
        assert right.snapshot is not None and right.observation is not None
        assert tuple(goal.target for goal in right.observation.goals) == (
            "True",
            "1 = 1",
            "True",
        )
        left = bridge.step(
            bridge.fork(before), Candidate(operation="constructor", goal_id="g0")
        )
        assert left.status == "advanced", left.diagnostics
        assert left.snapshot is not None and left.observation is not None
        assert tuple(goal.target for goal in left.observation.goals) == (
            "1 = 1 ∧ True",
        )
        assert bridge.observe(root) == initial
        assert bridge.observe(right.snapshot) == right.observation
        actions: tuple[Operation, ...] = ("reflexivity", "constructor", "constructor")
        current = right.snapshot
        for operation in actions:
            status = bridge.step(
                current,
                Candidate(
                    operation=operation,
                    goal_id="g1" if operation == "reflexivity" else "g0",
                ),
            )
            assert status.snapshot is not None and status.status in {
                "advanced",
                "closed",
            }, status.diagnostics
            right = status
            current = status.snapshot
        assert right.status == "closed"
    finally:
        bridge.close(root.session_id)


class _TimeoutFirstStep(SubprocessWorker):
    def __init__(self, lean: Path) -> None:
        super().__init__(
            (str(lean), "--threads=1", "--run", "AI4Algebra/Bridge/Main.lean"), _ROOT
        )
        self._first_step = True

    def request(
        self, request: WorkerRequest, timeout_seconds: float, cancelled: Event
    ) -> WorkerResult:
        if request.operation == "step" and self._first_step:
            self._first_step = False
            timeout_seconds = 0.05
        return super().request(request, timeout_seconds, cancelled)


def test_real_worker_timeout_recovers_parent() -> None:
    sysroot = (
        subprocess.run(
            ["lean", "--print-prefix"],
            cwd=_ROOT,
            check=True,
            capture_output=True,
            timeout=30,
        )
        .stdout.decode("utf-8")
        .strip()
    )
    lean = Path(sysroot) / "bin" / ("lean.exe" if os.name == "nt" else "lean")
    bridge = LeanBridge(_ROOT, worker=_TimeoutFirstStep(lean))
    root, initial = bridge.open(_problem("True"), _LIMITS)
    try:
        candidate = Candidate(operation="constructor", goal_id="g0")
        failed, usage = bridge.step_with_usage(root, candidate, max_worker_requests=2)
        assert failed.status == "timeout", failed.diagnostics
        assert failed.snapshot == root and failed.observation == initial
        assert usage == StepUsage(worker_requests=2, recovery_requests=1)
        completed, usage = bridge.step_with_usage(
            root, candidate, max_worker_requests=1
        )
        assert completed.status == "closed", completed.diagnostics
        assert completed.observation is not None and not completed.observation.goals
        assert usage == StepUsage(worker_requests=1)
    finally:
        bridge.close(root.session_id)
