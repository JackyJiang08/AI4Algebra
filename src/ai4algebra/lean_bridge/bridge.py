"""Immutable Lean sessions backed by isolated replay of validated action prefixes."""

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Lock
from typing import Literal, Protocol
from uuid import uuid4

from ai4algebra.config import Limits
from ai4algebra.contracts import (
    Candidate,
    Goal,
    Observation,
    Problem,
    Snapshot,
    StepResult,
    digest_json,
)

from .protocol import (
    LEAN_BUILD_COMMIT,
    LEAN_VERSION,
    MATHLIB_REVISION,
    BridgeError,
    BridgeTimeout,
    ProjectWorker,
    Worker,
    WorkerRequest,
    WorkerResult,
)

_LEAN_OPTIONS = (("autoImplicit", False), ("async", False))


class Bridge(Protocol):
    def open(
        self, problem: Problem, limits: Limits
    ) -> tuple[Snapshot, Observation]: ...
    def fork(self, snapshot: Snapshot) -> Snapshot: ...
    def observe(self, snapshot: Snapshot) -> Observation: ...
    def step(self, snapshot: Snapshot, candidate: Candidate) -> StepResult: ...
    def close(self, session_id: str) -> None: ...


def environment_digest(project_root: Path, imports: tuple[str, ...]) -> str:
    """Bind observations to the resolved Lake lock, toolchain and ordered imports."""
    try:
        toolchain = (
            (project_root / "lean-toolchain").read_text(encoding="utf-8").strip()
        )
        manifest = json.loads(
            (project_root / "lake-manifest.json").read_text(encoding="utf-8")
        )
        revisions = {
            package["name"]: package["rev"] for package in manifest["packages"]
        }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BridgeError("could not read pinned Lean project metadata") from exc
    if (
        toolchain != f"leanprover/lean4:v{LEAN_VERSION}"
        or revisions.get("mathlib") != MATHLIB_REVISION
    ):
        raise BridgeError(
            "Lean project environment does not match the toolchain and mathlib pins"
        )
    return digest_json((toolchain, LEAN_BUILD_COMMIT, manifest, _LEAN_OPTIONS, imports))


@dataclass(frozen=True)
class _State:
    prefix: tuple[Candidate, ...]
    observation: Observation


@dataclass
class _Session:
    id: str
    problem: Problem
    environment: str
    limits: Limits
    deadline: float
    cancelled: Event = field(default_factory=Event)
    states: dict[str, _State] = field(default_factory=dict)


class _RequestCancellation(Event):
    """Let a worker react to either session close or caller cancellation."""

    def __init__(self, closed: Event, cancelled: Event) -> None:
        super().__init__()
        self._closed = closed
        self._cancelled = cancelled

    def is_set(self) -> bool:
        return self._closed.is_set() or self._cancelled.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            delay = 0.01 if deadline is None else min(0.01, deadline - time.monotonic())
            if delay <= 0:
                return self.is_set()
            self._cancelled.wait(delay)
        return True


@dataclass(frozen=True)
class StepUsage:
    """Worker request attempts within one step, including failed recovery replays."""

    worker_requests: int = 0
    recovery_requests: int = 0


@dataclass
class _StepBudget:
    maximum: int | None
    usage: StepUsage = StepUsage()

    @property
    def exhausted(self) -> bool:
        return self.maximum is not None and self.usage.worker_requests >= self.maximum

    def charge(self, *, recovery: bool) -> None:
        if self.exhausted:
            raise BridgeError("Lean worker request budget exhausted")
        self.usage = StepUsage(
            worker_requests=self.usage.worker_requests + 1,
            recovery_requests=self.usage.recovery_requests + int(recovery),
        )


def _snapshot(session: _Session, prefix: tuple[Candidate, ...]) -> Snapshot:
    prefix_digest = digest_json(tuple(candidate.candidate_id for candidate in prefix))
    return Snapshot(
        session_id=session.id,
        environment_digest=session.environment,
        prefix_digest=prefix_digest,
        snapshot_id=digest_json(
            (
                session.id,
                session.environment,
                session.problem.statement_digest,
                prefix_digest,
            )
        ),
    )


def _check_references(candidate: Candidate, observation: Observation) -> str | None:
    goal = next(
        (goal for goal in observation.goals if goal.goal_id == candidate.goal_id), None
    )
    if goal is None:
        return "candidate refers to an unknown goal"
    locals_ = {hyp.local_id for hyp in goal.hypotheses}
    references = {arg.reference for arg in candidate.arguments if arg.kind == "local"}
    references.update(
        ref for ref in (candidate.local_id, candidate.location) if ref is not None
    )
    if not references <= locals_:
        return "candidate refers to an unknown local"
    return None


class LeanBridge:
    """Run checked prefixes in separate Lean invocations and retain verified observations."""

    def __init__(
        self,
        project_root: Path,
        *,
        worker: Worker | None = None,
        approved_imports: frozenset[str] = frozenset({"Init", "Mathlib", "Std"}),
        recovery_attempts: int = 1,
    ) -> None:
        if recovery_attempts < 0:
            raise ValueError("recovery attempts cannot be negative")
        self._root = project_root.resolve()
        self._worker: Worker = (
            worker if worker is not None else ProjectWorker(self._root, "observer")
        )
        self._approved_imports = approved_imports
        self._recovery_attempts = recovery_attempts
        self._sessions: dict[str, _Session] = {}
        self._lock = Lock()

    def open(
        self, problem: Problem, limits: Limits, *, cancelled: Event | None = None
    ) -> tuple[Snapshot, Observation]:
        if any(
            name not in self._approved_imports and not name.startswith("Mathlib.")
            for name in problem.imports
        ):
            raise BridgeError("problem includes an unapproved Lean import")
        session = _Session(
            id=uuid4().hex,
            problem=problem,
            environment=environment_digest(self._root, problem.imports),
            limits=limits,
            deadline=time.monotonic() + limits.task_timeout_seconds,
        )
        snapshot = _snapshot(session, ())
        reply = self._request(session, snapshot, (), cancelled=cancelled)
        if reply.status != "observed":
            raise BridgeError("Lean returned an invalid initial observation")
        goals = self._goals(reply)
        if not goals:
            raise BridgeError("Lean did not return an initial proof goal")
        observation = Observation(snapshot=snapshot, goals=goals)
        session.states[snapshot.snapshot_id] = _State((), observation)
        with self._lock:
            if cancelled is not None and cancelled.is_set():
                raise BridgeError("Lean request cancelled")
            self._sessions[session.id] = session
        return snapshot, observation

    def fork(self, snapshot: Snapshot) -> Snapshot:
        self._lookup(snapshot)
        return snapshot

    def observe(self, snapshot: Snapshot) -> Observation:
        session, state = self._lookup(snapshot)
        return self._replay(session, state)

    def step(
        self,
        snapshot: Snapshot,
        candidate: Candidate,
        *,
        timeout_seconds: float | None = None,
    ) -> StepResult:
        result, _ = self.step_with_usage(
            snapshot, candidate, timeout_seconds=timeout_seconds
        )
        return result

    def step_with_usage(
        self,
        snapshot: Snapshot,
        candidate: Candidate,
        *,
        timeout_seconds: float | None = None,
        max_worker_requests: int | None = None,
        cancelled: Event | None = None,
    ) -> tuple[StepResult, StepUsage]:
        """Bound a step and its recovery by the caller's remaining worker requests."""
        if max_worker_requests is not None and (
            type(max_worker_requests) is not int or max_worker_requests < 0
        ):
            raise ValueError("a worker request budget must be a nonnegative integer")
        budget = _StepBudget(max_worker_requests)
        result = self._step(snapshot, candidate, timeout_seconds, budget, cancelled)
        return result, budget.usage

    def _step(
        self,
        snapshot: Snapshot,
        candidate: Candidate,
        timeout_seconds: float | None,
        budget: _StepBudget,
        cancelled: Event | None,
    ) -> StepResult:
        try:
            session, parent = self._lookup(snapshot)
        except BridgeError as exc:
            return StepResult(status="infrastructure_error", diagnostics=(str(exc),))
        invalid = _check_references(candidate, parent.observation)
        if invalid is not None:
            return StepResult(
                status="rejected",
                snapshot=snapshot,
                observation=parent.observation,
                diagnostics=(invalid,),
            )
        deadline = None
        if timeout_seconds is not None:
            if not math.isfinite(timeout_seconds):
                raise ValueError("step timeout must be finite")
            deadline = time.monotonic() + timeout_seconds
        try:
            reply = self._request(
                session,
                snapshot,
                parent.prefix,
                candidate,
                deadline,
                budget=budget,
                cancelled=cancelled,
            )
            if reply.parent_goals != parent.observation.goals:
                raise BridgeError("Lean replay diverged from the parent observation")
            if reply.status == "rejected":
                return StepResult(
                    status="rejected",
                    snapshot=snapshot,
                    observation=parent.observation,
                    diagnostics=(reply.diagnostic or "Lean rejected the tactic",),
                )
            if reply.status not in {"advanced", "closed"}:
                raise BridgeError("Lean returned an invalid step result")
            prefix = (*parent.prefix, candidate)
            child = _snapshot(session, prefix)
            observation = Observation(snapshot=child, goals=self._goals(reply))
            with self._lock:
                if session.cancelled.is_set():
                    raise BridgeError("Lean session is closed")
                if cancelled is not None and cancelled.is_set():
                    raise BridgeError("Lean request cancelled")
                prior = session.states.get(child.snapshot_id)
                if prior is not None and prior.observation != observation:
                    raise BridgeError("Lean step diverged from a previous replay")
                session.states[child.snapshot_id] = _State(prefix, observation)
            return StepResult(
                status=reply.status, snapshot=child, observation=observation
            )
        except BridgeError as exc:
            return self._recover(session, parent, exc, deadline, budget, cancelled)

    def close(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is not None:
                session.cancelled.set()
                session.states.clear()

    def _lookup(self, snapshot: Snapshot) -> tuple[_Session, _State]:
        with self._lock:
            session = self._sessions.get(snapshot.session_id)
            if session is None:
                raise BridgeError("unknown or closed Lean session")
            state = session.states.get(snapshot.snapshot_id)
            if state is None or state.observation.snapshot != snapshot:
                raise BridgeError("stale or invalid Lean snapshot")
            return session, state

    def _request(
        self,
        session: _Session,
        snapshot: Snapshot,
        prefix: tuple[Candidate, ...],
        candidate: Candidate | None = None,
        deadline: float | None = None,
        *,
        budget: _StepBudget | None = None,
        cancelled: Event | None = None,
    ) -> WorkerResult:
        problem = session.problem
        request = WorkerRequest(
            request_id=uuid4().hex,
            session_id=session.id,
            environment_digest=session.environment,
            snapshot_id=snapshot.snapshot_id,
            prefix_digest=snapshot.prefix_digest,
            statement_digest=problem.statement_digest,
            operation="observe" if candidate is None else "step",
            imports=problem.imports,
            theorem_name=problem.lean_name,
            universes=problem.universes,
            binders=problem.binders,
            statement=problem.lean_statement,
            prefix=prefix,
            candidate=candidate,
        )
        task_deadline = (
            session.deadline if deadline is None else min(session.deadline, deadline)
        )
        timeout = min(
            session.limits.step_timeout_seconds, task_deadline - time.monotonic()
        )
        if timeout <= 0:
            raise BridgeTimeout("Lean session deadline expired")
        if session.cancelled.is_set():
            raise BridgeError("Lean session is closed")
        signal = session.cancelled
        if cancelled is not None:
            if cancelled.is_set():
                raise BridgeError("Lean request cancelled")
            signal = _RequestCancellation(session.cancelled, cancelled)
        if budget is not None:
            budget.charge(recovery=candidate is None)
        response = self._worker.request(request, timeout, signal)
        if session.cancelled.is_set():
            raise BridgeError("Lean session is closed")
        if cancelled is not None and cancelled.is_set():
            raise BridgeError("Lean request cancelled")
        return response

    def _replay(
        self,
        session: _Session,
        state: _State,
        deadline: float | None = None,
        *,
        budget: _StepBudget | None = None,
        cancelled: Event | None = None,
    ) -> Observation:
        result = self._request(
            session,
            state.observation.snapshot,
            state.prefix,
            deadline=deadline,
            budget=budget,
            cancelled=cancelled,
        )
        if result.status != "observed" or result.goals != state.observation.goals:
            raise BridgeError("Lean replay diverged from the stored observation")
        return state.observation

    def _recover(
        self,
        session: _Session,
        parent: _State,
        failure: BridgeError,
        deadline: float | None,
        budget: _StepBudget,
        cancelled: Event | None,
    ) -> StepResult:
        status: Literal["timeout", "infrastructure_error"] = (
            "timeout" if isinstance(failure, BridgeTimeout) else "infrastructure_error"
        )
        diagnostics = [str(failure)]
        for _ in range(self._recovery_attempts):
            if session.cancelled.is_set() or (
                cancelled is not None and cancelled.is_set()
            ):
                break
            if budget.exhausted:
                if budget.usage.worker_requests:
                    diagnostics.append(
                        "Lean parent recovery skipped at the worker request limit"
                    )
                break
            try:
                observation = self._replay(
                    session, parent, deadline, budget=budget, cancelled=cancelled
                )
            except BridgeError as exc:
                diagnostics.append(f"Lean parent recovery failed: {exc}")
            else:
                return StepResult(
                    status=status,
                    snapshot=observation.snapshot,
                    observation=observation,
                    diagnostics=tuple(diagnostics),
                )
        return StepResult(status=status, diagnostics=tuple(diagnostics))

    @staticmethod
    def _goals(reply: WorkerResult) -> tuple[Goal, ...]:
        if reply.goals is None or len({goal.goal_id for goal in reply.goals}) != len(
            reply.goals
        ):
            raise BridgeError("Lean returned an invalid goal observation")
        return reply.goals
