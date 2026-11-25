"""Typed framing and process ownership for the pinned Lean observer."""

import math
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from io import BufferedReader
from pathlib import Path
from threading import Event, Thread
from typing import Literal, Protocol

from pydantic import ValidationError, model_validator
from typing_extensions import Self

from ai4algebra.contracts import (
    Candidate,
    Digest,
    Goal,
    Identifier,
    LeanName,
    NonBlank,
    Record,
)

LEAN_VERSION = "4.34.0-rc1"
LEAN_BUILD_COMMIT = "3447a668783dbce1a8fdb97101dd067687b2b418"
MATHLIB_REVISION = "de5ce8a9a66a4aa68a9bdbb35b63a06d34d9ca11"


class BridgeError(RuntimeError):
    """Lean did not yield a usable observation."""


class BridgeTimeout(BridgeError):
    """Lean exceeded its subprocess deadline."""


class WorkerRequest(Record):
    request_id: Identifier
    session_id: Identifier
    operation: Literal["observe", "step"]
    environment_digest: Digest
    snapshot_id: Identifier
    prefix_digest: Digest
    statement_digest: Digest
    imports: tuple[LeanName, ...]
    theorem_name: LeanName
    universes: tuple[LeanName, ...]
    binders: tuple[NonBlank, ...]
    statement: NonBlank
    prefix: tuple[Candidate, ...]
    candidate: Candidate | None = None

    @model_validator(mode="after")
    def _check_candidate(self) -> Self:
        if (self.operation == "step") != (self.candidate is not None):
            raise ValueError("candidate is required exactly for step requests")
        return self


class WorkerResult(Record):
    status: Literal["observed", "advanced", "closed", "rejected", "error"]
    goals: tuple[Goal, ...] | None = None
    parent_goals: tuple[Goal, ...] | None = None
    diagnostic: NonBlank | None = None

    @model_validator(mode="after")
    def _check_result(self) -> Self:
        if self.status in {"observed", "advanced", "closed"}:
            if self.goals is None or self.diagnostic is not None:
                raise ValueError("a successful response requires goals")
            if self.status == "advanced" and not self.goals:
                raise ValueError("an advanced result requires remaining goals")
            if self.status == "closed" and self.goals:
                raise ValueError("closure requires an empty goal list")
        elif self.goals is not None or self.diagnostic is None:
            raise ValueError("an unsuccessful response requires a diagnostic")
        has_parent = self.status in {"advanced", "closed", "rejected"}
        if has_parent != (self.parent_goals is not None):
            raise ValueError("unexpected parent observation")
        return self


class WorkerResponse(Record):
    request_id: Identifier
    session_id: Identifier
    environment_digest: Digest
    snapshot_id: Identifier
    prefix_digest: Digest
    statement_digest: Digest
    lean_version: NonBlank
    result: WorkerResult

    def validate_for(self, request: WorkerRequest) -> None:
        actual = (
            self.request_id,
            self.session_id,
            self.environment_digest,
            self.snapshot_id,
            self.prefix_digest,
            self.statement_digest,
        )
        expected = (
            request.request_id,
            request.session_id,
            request.environment_digest,
            request.snapshot_id,
            request.prefix_digest,
            request.statement_digest,
        )
        if actual != expected:
            raise BridgeError(
                "Lean worker response identifiers do not match the request"
            )
        if self.lean_version != LEAN_VERSION:
            raise BridgeError("Lean worker toolchain does not match the project pin")
        if self.result.status == "error":
            raise BridgeError(self.result.diagnostic or "Lean worker error")
        if (request.operation == "observe") != (self.result.status == "observed"):
            raise BridgeError("Lean worker returned the wrong result for the operation")


class Worker(Protocol):
    def request(
        self, request: WorkerRequest, timeout_seconds: float, cancelled: Event
    ) -> WorkerResult: ...


def _worker_environment() -> dict[str, str]:
    names = {
        "APPDATA",
        "ELAN_HOME",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LANG",
        "LOCALAPPDATA",
        "PATH",
        "PROGRAMDATA",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    return {name: value for name, value in os.environ.items() if name.upper() in names}


def _windows_job(pid: int) -> Callable[[], None] | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL

    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return None
    # AssignProcessToJobObject requires PROCESS_SET_QUOTA and PROCESS_TERMINATE.
    handle = kernel.OpenProcess(0x0100 | 0x0001, False, pid)
    if not handle:
        kernel.CloseHandle(job)
        return None
    assigned = kernel.AssignProcessToJobObject(job, handle)
    kernel.CloseHandle(handle)
    if not assigned:
        kernel.CloseHandle(job)
        return None

    def terminate() -> None:
        kernel.TerminateJobObject(job, 1)
        kernel.CloseHandle(job)

    return terminate


def _stop_process_tree(
    process: subprocess.Popen[bytes], terminate_job: Callable[[], None] | None
) -> None:
    if terminate_job is not None:
        terminate_job()
    elif sys.platform == "win32":
        if process.poll() is None:
            try:
                subprocess.run(
                    ["taskkill.exe", "/F", "/T", "/PID", str(process.pid)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=2,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
            if process.poll() is None:
                process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=2)


class SubprocessWorker:
    """Start one process per frame and bound both output pipes as they are read."""

    def __init__(
        self,
        argv: tuple[str, ...],
        cwd: Path,
        *,
        max_input_bytes: int = 1_048_576,
        max_output_bytes: int = 1_048_576,
        max_diagnostic_bytes: int = 65_536,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        if (
            not argv
            or min(max_input_bytes, max_output_bytes, max_diagnostic_bytes) <= 0
        ):
            raise ValueError("worker command and byte limits are required")
        self._argv = argv
        self._cwd = cwd
        self._max_input_bytes = max_input_bytes
        self._max_output_bytes = max_output_bytes
        self._max_diagnostic_bytes = max_diagnostic_bytes
        self._environment = dict(environment or {})

    def request(
        self, request: WorkerRequest, timeout_seconds: float, cancelled: Event
    ) -> WorkerResult:
        frame = (request.to_json() + "\n").encode("utf-8")
        if len(frame) > self._max_input_bytes:
            raise BridgeError("Lean worker request exceeds its byte limit")
        output = self.exchange(frame, timeout_seconds, cancelled)
        try:
            decoded = output.decode("utf-8", errors="strict")
            if not decoded.endswith("\n") or decoded.count("\n") != 1:
                raise BridgeError(
                    "Lean worker response must contain one complete JSON frame"
                )
            response = WorkerResponse.from_json(decoded)
        except (ValidationError, ValueError) as exc:
            raise BridgeError("Lean worker returned an invalid JSON frame") from exc
        response.validate_for(request)
        return response.result

    def exchange(self, frame: bytes, timeout_seconds: float, cancelled: Event) -> bytes:
        if len(frame) > self._max_input_bytes:
            raise BridgeError("Lean worker request exceeds its byte limit")
        if not math.isfinite(timeout_seconds):
            raise ValueError("Lean worker timeout must be finite")
        if timeout_seconds <= 0:
            raise BridgeTimeout("Lean worker deadline expired")
        if cancelled.is_set():
            raise BridgeError("Lean session is closed")
        deadline = time.monotonic() + timeout_seconds
        try:
            process = subprocess.Popen(
                self._argv,
                cwd=self._cwd,
                env=_worker_environment() | self._environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name != "nt",
            )
        except OSError as exc:
            raise BridgeError("Lean worker could not start") from exc

        terminate_job = _windows_job(process.pid)
        stdin, stdout, stderr = process.stdin, process.stdout, process.stderr
        assert stdin is not None
        assert isinstance(stdout, BufferedReader) and isinstance(stderr, BufferedReader)
        too_large = Event()
        pipe_failure = Event()
        response, diagnostics = bytearray(), bytearray()

        def read(stream: BufferedReader, buffer: bytearray, limit: int) -> None:
            with stream:
                while chunk := stream.read1(min(8192, limit - len(buffer) + 1)):
                    if len(chunk) + len(buffer) > limit:
                        too_large.set()
                        return
                    buffer.extend(chunk)

        def write() -> None:
            with stdin:
                stdin.write(frame)

        def guard(operation: Callable[[], None]) -> None:
            try:
                operation()
            except (BrokenPipeError, OSError, ValueError):
                pipe_failure.set()

        threads = [
            Thread(target=guard, args=(write,), daemon=True),
            Thread(
                target=guard,
                args=(lambda: read(stdout, response, self._max_output_bytes),),
                daemon=True,
            ),
            Thread(
                target=guard,
                args=(lambda: read(stderr, diagnostics, self._max_diagnostic_bytes),),
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()
        try:
            while process.poll() is None or any(
                thread.is_alive() for thread in threads
            ):
                if too_large.is_set():
                    raise BridgeError("Lean worker exceeded its output byte limit")
                if cancelled.is_set():
                    raise BridgeError("Lean session is closed")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise BridgeTimeout("Lean worker deadline expired")
                cancelled.wait(min(remaining, 0.01))
            if too_large.is_set():
                raise BridgeError("Lean worker exceeded its output byte limit")
            if time.monotonic() > deadline:
                raise BridgeTimeout("Lean worker deadline expired")
            if process.returncode != 0:
                detail = diagnostics.decode("utf-8", errors="replace").strip()
                raise BridgeError(
                    f"Lean worker exited with status {process.returncode}"
                    + (f": {detail}" if detail else "")
                )
            if pipe_failure.is_set():
                raise BridgeError("Lean worker pipe failed")
        finally:
            try:
                _stop_process_tree(process, terminate_job)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise BridgeError(
                    "Lean worker process tree could not be reaped"
                ) from exc
            for thread in threads:
                thread.join(timeout=0.2)
        return bytes(response)


_OBSERVER_SOURCE = Path("AI4Algebra/Bridge/Main.lean")
_VERIFIER_SOURCE = Path("AI4Algebra/Verification/Main.lean")
_VERIFIER_MODULES = (
    _OBSERVER_SOURCE,
    Path("AI4Algebra/Verification/Audit.lean"),
    Path("AI4Algebra/Verification/Replay.lean"),
)
_RUNTIME_KEYS = {
    "LEAN_PATH",
    "LEAN_SYSROOT",
    "PATH",
    "DYLD_LIBRARY_PATH",
    "LD_LIBRARY_PATH",
}


class ProjectWorker(SubprocessWorker):
    """Use a fresh native worker, with the validated interpreted path as a fallback."""

    def __init__(
        self, project_root: Path, kind: Literal["observer", "verifier"]
    ) -> None:
        source = _OBSERVER_SOURCE if kind == "observer" else _VERIFIER_SOURCE
        super().__init__(
            ("lake", "env", "lean", "--threads=1", "--run", source.as_posix()),
            project_root,
        )
        extension = ".exe" if os.name == "nt" else ""
        self._binary = (
            project_root / ".lake/build/bin" / f"ai4algebra-{kind}{extension}"
        )
        self._compiled_modules = _VERIFIER_MODULES if kind == "verifier" else ()
        self._sources = (source, *self._compiled_modules)
        self._native: tuple[tuple[int, ...], SubprocessWorker] | None = None

    def exchange(self, frame: bytes, timeout_seconds: float, cancelled: Event) -> bytes:
        deadline = time.monotonic() + timeout_seconds
        self._check_compiled_modules()
        fingerprint = self._native_fingerprint()
        if fingerprint is None:
            return super().exchange(frame, deadline - time.monotonic(), cancelled)
        native = self._native
        if native is None or native[0] != fingerprint:
            runtime = SubprocessWorker(("lake", "env"), self._cwd)
            data = runtime.exchange(b"", deadline - time.monotonic(), cancelled)
            environment = self._decode_runtime(data)
            native = (
                fingerprint,
                SubprocessWorker(
                    (str(self._binary),), self._cwd, environment=environment
                ),
            )
            self._native = native
        return native[1].exchange(frame, deadline - time.monotonic(), cancelled)

    def _check_compiled_modules(self) -> None:
        library = self._cwd / ".lake/build/lib/lean"
        try:
            for source in self._compiled_modules:
                compiled = library / source.with_suffix(".olean")
                if (
                    compiled.stat().st_mtime_ns
                    < (self._cwd / source).stat().st_mtime_ns
                ):
                    raise BridgeError(
                        "Lean verifier modules are stale. Run lake build."
                    )
        except OSError as exc:
            raise BridgeError(
                "Lean verifier modules are missing. Run lake build."
            ) from exc

    def _native_fingerprint(self) -> tuple[int, ...] | None:
        try:
            binary_time = self._binary.stat().st_mtime_ns
            inputs = (
                *self._sources,
                Path("lean-toolchain"),
                Path("lakefile.toml"),
                Path("lake-manifest.json"),
            )
            times = tuple((self._cwd / source).stat().st_mtime_ns for source in inputs)
        except OSError:
            return None
        if binary_time < max(times):
            return None
        return binary_time, *times

    @staticmethod
    def _decode_runtime(data: bytes) -> dict[str, str]:
        try:
            lines = data.decode("utf-8", errors="strict").splitlines()
        except UnicodeDecodeError as exc:
            raise BridgeError("Lake returned an invalid runtime environment") from exc
        environment = {}
        for line in lines:
            key, separator, value = line.partition("=")
            if separator and key in _RUNTIME_KEYS:
                environment[key] = value
        if any(
            not environment.get(key) for key in ("LEAN_SYSROOT", "LEAN_PATH", "PATH")
        ):
            raise BridgeError("Lake did not supply the Lean runtime directories")
        return environment
