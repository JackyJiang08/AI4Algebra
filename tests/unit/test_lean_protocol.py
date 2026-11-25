"""Verify worker framing and session failure handling without Lean."""

import os
import sys
import time
from collections import deque
from pathlib import Path
from threading import Event

import pytest

from ai4algebra.config import Limits
from ai4algebra.contracts import Candidate, Goal, Problem, SourceRef, digest_json
from ai4algebra.lean_bridge import BridgeError, BridgeTimeout, LeanBridge, StepUsage
from ai4algebra.lean_bridge.protocol import (
    ProjectWorker,
    SubprocessWorker,
    WorkerRequest,
    WorkerResult,
)

_ROOT = Path(__file__).resolve().parents[2]


def test_raw_exchange_rejects_oversize_input_before_launch(tmp_path: Path) -> None:
    worker = SubprocessWorker(("must-not-launch",), tmp_path, max_input_bytes=4)
    with pytest.raises(BridgeError, match="byte limit"):
        worker.exchange(b"12345", 1.0, Event())


@pytest.mark.parametrize("timeout", [float("nan"), float("inf")])
def test_raw_exchange_requires_finite_timeout(tmp_path: Path, timeout: float) -> None:
    worker = SubprocessWorker(("must-not-launch",), tmp_path)
    with pytest.raises(ValueError, match="finite"):
        worker.exchange(b"{}\n", timeout, Event())


_DIGEST = digest_json("fixture")
_GOAL = Goal(goal_id="g0", target="True", expression='["const","True",[]]')
_OBSERVED = WorkerResult(status="observed", goals=(_GOAL,))
_ACTION = Candidate(operation="constructor", goal_id="g0")
_VALID_RESPONSE = """
import json, sys
request = json.loads(sys.stdin.buffer.readline())
fields = ("request_id", "session_id", "snapshot_id", "environment_digest",
          "prefix_digest", "statement_digest")
frame = {key: request[key] for key in fields}
frame.update(schema_version=1, lean_version="4.34.0-rc1",
             result={"schema_version": 1, "status": "observed", "goals": []})
"""


def _request() -> WorkerRequest:
    return WorkerRequest(
        request_id="request-1",
        session_id="session-1",
        operation="observe",
        environment_digest=_DIGEST,
        snapshot_id="snapshot-1",
        prefix_digest=_DIGEST,
        statement_digest=_DIGEST,
        imports=(),
        theorem_name="example_fixture",
        universes=(),
        binders=(),
        statement="True",
        prefix=(),
    )


def _problem(imports: tuple[str, ...] = ()) -> Problem:
    return Problem(
        task_id="protocol-fixture",
        source=SourceRef(
            kind="fixture",
            source_id="protocol-fixture",
            revision="1",
            location="tests/unit/test_lean_protocol.py",
            content_digest=_DIGEST,
            attribution="AI4Algebra",
            license_ref="MIT",
        ),
        informal_statement="True",
        family_id="protocol-fixtures",
        split="train",
        imports=imports,
        lean_name="example_fixture",
        lean_statement="True",
        mapping_evidence_id="protocol-fixture",
    )


def test_typed_worker_accepts_one_valid_frame(tmp_path: Path) -> None:
    command = _VALID_RESPONSE + "print(json.dumps(frame))"
    result = SubprocessWorker((sys.executable, "-c", command), tmp_path).request(
        _request(), 5.0, Event()
    )
    assert result == WorkerResult(status="observed", goals=())


@pytest.mark.parametrize(
    ("command", "message"),
    [
        ("""sys.stdout.write(json.dumps(frame))""", "one complete"),
        ("""print(json.dumps(frame)); print(json.dumps(frame))""", "one complete"),
        ("""print("broken JSON")""", "invalid JSON"),
        (r"""sys.stdout.buffer.write(b"\xff\n")""", "invalid JSON"),
        (
            """print(json.dumps(frame).replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1))""",
            "invalid JSON",
        ),
        ("""frame.pop("schema_version"); print(json.dumps(frame))""", "invalid JSON"),
        (
            """frame["schema_version"] = True; print(json.dumps(frame))""",
            "invalid JSON",
        ),
        (
            """frame["result"].pop("schema_version"); print(json.dumps(frame))""",
            "invalid JSON",
        ),
        (
            """frame["result"]["extra"] = True; print(json.dumps(frame))""",
            "invalid JSON",
        ),
        ("""frame["request_id"] = "stale"; print(json.dumps(frame))""", "identifiers"),
        (
            """frame["statement_digest"] = "9" * 64; print(json.dumps(frame))""",
            "identifiers",
        ),
        ("""frame["lean_version"] = "4.35.0"; print(json.dumps(frame))""", "toolchain"),
        (
            """sys.stderr.write("crash details"); sys.exit(7)""",
            "status 7: crash details",
        ),
        ("""print("x" * 10000)""", "output byte limit"),
        ("""sys.stderr.write("x" * 10000)""", "output byte limit"),
    ],
)
def test_worker_rejects_invalid_frames(
    tmp_path: Path, command: str, message: str
) -> None:
    worker = SubprocessWorker(
        (sys.executable, "-c", _VALID_RESPONSE + command),
        tmp_path,
        max_output_bytes=4096,
        max_diagnostic_bytes=4096,
    )
    with pytest.raises(BridgeError, match=message):
        worker.request(_request(), 5.0, Event())


def test_worker_times_out_and_kills_descendants(tmp_path: Path) -> None:
    child_code = (
        "import time; from pathlib import Path; time.sleep(1); Path('orphan').touch()"
    )
    command = (
        _VALID_RESPONSE
        + "import subprocess, time\n"
        + f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        + "time.sleep(20)\n"
    )
    worker = SubprocessWorker((sys.executable, "-c", command), tmp_path)
    started = time.monotonic()
    with pytest.raises(BridgeTimeout):
        worker.request(_request(), 0.5, Event())
    assert time.monotonic() - started < 5.0
    time.sleep(1)
    assert not (tmp_path / "orphan").exists()


def test_worker_reports_byte_limit_before_process_exits(tmp_path: Path) -> None:
    command = (
        _VALID_RESPONSE + 'print("x" * 5000, flush=True); import time; time.sleep(10)'
    )
    worker = SubprocessWorker(
        (sys.executable, "-c", command),
        tmp_path,
        max_output_bytes=4096,
    )
    with pytest.raises(BridgeError, match="output byte limit"):
        worker.request(_request(), 5.0, Event())


def test_worker_enforces_input_budget_and_cancel(tmp_path: Path) -> None:
    worker = SubprocessWorker((sys.executable, "-c", ""), tmp_path, max_input_bytes=1)
    with pytest.raises(BridgeError, match="request exceeds"):
        worker.request(_request(), 5.0, Event())
    cancelled = Event()
    cancelled.set()
    worker = SubprocessWorker((sys.executable, "-c", ""), tmp_path)
    with pytest.raises(BridgeError, match="closed"):
        worker.request(_request(), 5.0, cancelled)


def test_project_worker_prefers_fresh_native_and_falls_back_after_source_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "AI4Algebra/Bridge/Main.lean"
    source.parent.mkdir(parents=True)
    source.touch()
    for name in ("lean-toolchain", "lakefile.toml", "lake-manifest.json"):
        (tmp_path / name).touch()
    suffix = ".exe" if os.name == "nt" else ""
    binary = tmp_path / ".lake/build/bin" / f"ai4algebra-observer{suffix}"
    binary.parent.mkdir(parents=True)
    binary.touch()
    newer = time.time_ns() + 1_000_000_000
    os.utime(binary, ns=(newer, newer))

    calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

    def exchange(
        worker: SubprocessWorker, frame: bytes, timeout_seconds: float, cancelled: Event
    ) -> bytes:
        assert timeout_seconds > 0 and not cancelled.is_set()
        calls.append((worker._argv, worker._environment))
        if worker._argv == ("lake", "env"):
            assert frame == b""
            return b"LEAN_PATH=libs=one\nLEAN_SYSROOT=lean\nPATH=bin\nOPENAI_API_KEY=ignored\n"
        assert frame == b"payload"
        return b"response"

    monkeypatch.setattr(SubprocessWorker, "exchange", exchange)
    worker = ProjectWorker(tmp_path, "observer")
    assert worker.exchange(b"payload", 5.0, Event()) == b"response"
    assert worker.exchange(b"payload", 5.0, Event()) == b"response"
    latest = newer + 1_000_000_000
    os.utime(source, ns=(latest, latest))
    assert worker.exchange(b"payload", 5.0, Event()) == b"response"
    native_environment = {
        "LEAN_PATH": "libs=one",
        "LEAN_SYSROOT": "lean",
        "PATH": "bin",
    }
    assert calls == [
        (("lake", "env"), {}),
        ((str(binary),), native_environment),
        ((str(binary),), native_environment),
        (
            (
                "lake",
                "env",
                "lean",
                "--threads=1",
                "--run",
                "AI4Algebra/Bridge/Main.lean",
            ),
            {},
        ),
    ]


def test_verifier_requires_compiled_support_before_running(tmp_path: Path) -> None:
    worker = ProjectWorker(tmp_path, "verifier")
    with pytest.raises(BridgeError, match="Run lake build"):
        worker.exchange(b"payload", 5.0, Event())


class _FakeWorker:
    def __init__(self, *outcomes: WorkerResult | BridgeError) -> None:
        self.outcomes = deque(outcomes)
        self.requests: list[WorkerRequest] = []

    def request(
        self, request: WorkerRequest, timeout_seconds: float, cancelled: Event
    ) -> WorkerResult:
        assert timeout_seconds > 0 and not cancelled.is_set()
        self.requests.append(request)
        result = self.outcomes.popleft()
        if isinstance(result, BridgeError):
            raise result
        return result


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (BridgeError("simulated crash"), "infrastructure_error"),
        (BridgeTimeout("slow"), "timeout"),
    ],
)
def test_recovery_reobserves_actual_parent(failure: BridgeError, status: str) -> None:
    worker = _FakeWorker(_OBSERVED, failure, _OBSERVED)
    bridge = LeanBridge(_ROOT, worker=worker)
    snapshot, observed = bridge.open(_problem(), Limits())
    try:
        result, usage = bridge.step_with_usage(snapshot, _ACTION, max_worker_requests=2)
        assert result.status == status
        assert usage == StepUsage(worker_requests=2, recovery_requests=1)
        assert result.observation == observed and result.snapshot == snapshot
        assert [request.operation for request in worker.requests] == [
            "observe",
            "step",
            "observe",
        ]
        assert [request.snapshot_id for request in worker.requests] == [
            snapshot.snapshot_id
        ] * 3
    finally:
        bridge.close(snapshot.session_id)


def test_failed_recovery_does_not_return_cached_goals_or_closure() -> None:
    worker = _FakeWorker(
        _OBSERVED, BridgeError("simulated crash"), BridgeTimeout("slow")
    )
    bridge = LeanBridge(_ROOT, worker=worker)
    snapshot, _ = bridge.open(_problem(), Limits())
    try:
        result = bridge.step(snapshot, _ACTION)
        assert result.status == "infrastructure_error"
        assert result.snapshot is None and result.observation is None
        assert len(result.diagnostics) == 2
    finally:
        bridge.close(snapshot.session_id)


@pytest.mark.parametrize("maximum", [1, 2])
def test_worker_limit_caps_failed_step_and_recovery(maximum: int) -> None:
    worker = _FakeWorker(
        _OBSERVED,
        BridgeError("attempt failed"),
        BridgeTimeout("replay timed out"),
        _OBSERVED,
    )
    bridge = LeanBridge(_ROOT, worker=worker, recovery_attempts=3)
    snapshot, _ = bridge.open(_problem(), Limits())
    try:
        result, usage = bridge.step_with_usage(
            snapshot, _ACTION, max_worker_requests=maximum
        )
        assert result.status == "infrastructure_error"
        assert result.observation is None and result.snapshot is None
        assert usage == StepUsage(
            worker_requests=maximum, recovery_requests=maximum - 1
        )
        assert len(worker.requests) == 1 + maximum
        assert "worker request limit" in result.diagnostics[-1]
    finally:
        bridge.close(snapshot.session_id)


def test_undispatched_steps_do_not_charge_worker_requests() -> None:
    worker = _FakeWorker(_OBSERVED)
    bridge = LeanBridge(_ROOT, worker=worker)
    snapshot, _ = bridge.open(_problem(), Limits())
    try:
        no_budget, usage = bridge.step_with_usage(
            snapshot, _ACTION, max_worker_requests=0
        )
        assert no_budget.status == "infrastructure_error"
        assert "budget exhausted" in no_budget.diagnostics[0]
        assert usage == StepUsage()
        expired, usage = bridge.step_with_usage(snapshot, _ACTION, timeout_seconds=0)
        assert expired.status == "timeout"
        assert usage == StepUsage()
        invalid_candidate = Candidate(operation="constructor", goal_id="g99")
        invalid, usage = bridge.step_with_usage(snapshot, invalid_candidate)
        assert invalid.status == "rejected"
        assert usage == StepUsage()
        assert len(worker.requests) == 1
        with pytest.raises(ValueError, match="nonnegative"):
            bridge.step_with_usage(snapshot, _ACTION, max_worker_requests=-1)
    finally:
        bridge.close(snapshot.session_id)


def test_diverged_parent_and_stale_snapshot_cannot_close() -> None:
    divergent = WorkerResult(status="closed", goals=(), parent_goals=())
    worker = _FakeWorker(_OBSERVED, divergent, _OBSERVED)
    bridge = LeanBridge(_ROOT, worker=worker)
    snapshot, observed = bridge.open(_problem(), Limits())
    try:
        stale = snapshot.model_copy(update={"prefix_digest": _DIGEST})
        stale_result = bridge.step(stale, _ACTION)
        assert stale_result.status == "infrastructure_error"
        assert stale_result.observation is None
        divergent_result = bridge.step(snapshot, _ACTION)
        assert divergent_result.status == "infrastructure_error"
        assert divergent_result.observation == observed
        assert "diverged" in divergent_result.diagnostics[0]
    finally:
        bridge.close(snapshot.session_id)


def test_unapproved_import_never_reaches_worker() -> None:
    worker = _FakeWorker()
    bridge = LeanBridge(_ROOT, worker=worker)
    with pytest.raises(BridgeError, match="unapproved"):
        bridge.open(_problem(("Dangerous.Module",)), Limits())
    assert worker.requests == []
