"""Compose fresh Lean tools and a proposer shared within an experiment run."""

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Literal, Protocol

from ai4algebra.candidates import (
    BudgetLedger,
    CandidateGenerator,
    OpenAIProposer,
    TacticProposer,
)
from ai4algebra.config import RunConfig
from ai4algebra.contracts import Certificate, Problem, Record, Verdict
from ai4algebra.corpus import Corpus
from ai4algebra.lean_bridge import LeanBridge
from ai4algebra.lean_bridge.protocol import ProjectWorker
from ai4algebra.representation import FeatureEncoder
from ai4algebra.search import (
    ActionPolicy,
    SearchMode,
    SearchOptions,
    SearchReport,
    solve,
)
from ai4algebra.verification import Verifier

from ._artifacts import RunDirectory, premise_index


class ApiAccounting(Record):
    budget_usd: str = "0"
    settled_usd: str = "0"
    outstanding_usd: str = "0"
    reserved_requests: int = 0
    unresolved_requests: int = 0
    settled_input_tokens: int = 0
    settled_output_tokens: int = 0
    settled_cached_tokens: int = 0
    blocked: bool = False


class LeanCalls(Record):
    observer_requests: int = 0
    verifier_requests: int = 0

    @property
    def total(self) -> int:
        return self.observer_requests + self.verifier_requests


@dataclass(frozen=True)
class TaskExecution:
    report: SearchReport
    lean_calls: LeanCalls
    api_before: ApiAccounting | None = None


class SearchRuntime(Protocol):
    def search(
        self,
        problem: Problem,
        *,
        mode: SearchMode,
        options: SearchOptions,
        episode_id: str,
        policy: ActionPolicy | None = None,
        encoder: FeatureEncoder | None = None,
        collection_step: int = 0,
    ) -> TaskExecution: ...

    def api_accounting(self) -> ApiAccounting: ...


class _CountedWorker(ProjectWorker):
    def __init__(self, root: Path, kind: Literal["observer", "verifier"]) -> None:
        super().__init__(root, kind)
        self.calls = 0

    def exchange(self, frame: bytes, timeout_seconds: float, cancelled: Event) -> bytes:
        self.calls += 1
        return super().exchange(frame, timeout_seconds, cancelled)


class ProofRuntime:
    def __init__(
        self,
        corpus: Corpus,
        root: Path,
        config: RunConfig,
        directory: RunDirectory,
        run_id: str,
        *,
        proposer: TacticProposer | None = None,
    ) -> None:
        self._corpus = corpus
        self._root = root
        self._config = config
        self._directory = directory
        self._run_id = run_id
        self._ledger: BudgetLedger | None = None
        self._proposer = proposer

    def _enable_provider(self) -> None:
        if self._config.paid_enabled and self._proposer is None:
            self._directory.root.mkdir(parents=True, exist_ok=True)
            self._ledger = BudgetLedger(
                self._directory.path("provider-budget.sqlite"),
                self._run_id,
                self._config.api_budget_usd,
            )
            self._proposer = OpenAIProposer(self._config, self._ledger)

    def api_accounting(self) -> ApiAccounting:
        if self._ledger is None:
            return ApiAccounting(
                budget_usd=str(self._config.api_budget_usd)
                if self._config.paid_enabled
                else "0"
            )
        summary = self._ledger.summary()
        return ApiAccounting(
            budget_usd=str(summary.budget_usd),
            settled_usd=str(summary.spent_usd),
            outstanding_usd=str(summary.outstanding_usd),
            reserved_requests=summary.requests,
            unresolved_requests=summary.unresolved,
            settled_input_tokens=summary.input_tokens,
            settled_output_tokens=summary.output_tokens,
            settled_cached_tokens=summary.cached_tokens,
            blocked=summary.blocked,
        )

    def search(
        self,
        problem: Problem,
        *,
        mode: SearchMode,
        options: SearchOptions,
        episode_id: str,
        policy: ActionPolicy | None = None,
        encoder: FeatureEncoder | None = None,
        collection_step: int = 0,
    ) -> TaskExecution:
        self._enable_provider()
        api_before = self.api_accounting()
        observer = _CountedWorker(self._root, "observer")
        auditor = _CountedWorker(self._root, "verifier")
        bridge = LeanBridge(self._root, worker=observer)
        verifier = Verifier(
            self._root,
            timeout_seconds=self._config.limits.step_timeout_seconds,
            transport=auditor,
        )
        eligibility = self._corpus.eligibility_policy(problem)
        generator = CandidateGenerator(
            problem,
            eligibility,
            bridge,
            premise_index=premise_index(self._corpus, problem, self._root),
            proposer=self._proposer,
        )
        report = solve(
            problem,
            eligibility,
            bridge,
            generator,
            verifier,
            self._config.limits,
            mode=mode,
            options=options,
            episode_id=episode_id,
            policy=policy,
            encoder=encoder,
            collection_step=collection_step,
        )
        return TaskExecution(
            report,
            LeanCalls(
                observer_requests=observer.calls, verifier_requests=auditor.calls
            ),
            api_before,
        )

    def verify(
        self, problem: Problem, certificate: Certificate
    ) -> tuple[Verdict, LeanCalls]:
        auditor = _CountedWorker(self._root, "verifier")
        verdict = Verifier(
            self._root,
            timeout_seconds=self._config.limits.task_timeout_seconds,
            transport=auditor,
        ).verify(
            problem,
            certificate,
            self._corpus.eligibility_policy(problem),
            timeout_seconds=self._config.limits.task_timeout_seconds,
        )
        return verdict, LeanCalls(verifier_requests=auditor.calls)
