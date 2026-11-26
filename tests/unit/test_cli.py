"""Command-line validation and redacted offline reports without Lean subprocesses."""

import subprocess
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO, TextIOWrapper
from pathlib import Path
from threading import Barrier

import pytest

from ai4algebra.cli import _SolveResult, main
from ai4algebra.config import RunConfig, load_config
from ai4algebra.contracts import (
    Candidate,
    Certificate,
    Problem,
    Record,
    Verdict,
    digest_json,
)
from ai4algebra.corpus import Corpus
from ai4algebra.search import (
    ActionPolicy,
    SearchMode,
    SearchOptions,
    SearchReport,
    Work,
)
from ai4algebra.training._artifacts import (
    ArtifactRef,
    CatalogIdentity,
    RunDirectory,
    _revision,
)
from ai4algebra.training._runtime import (
    ApiAccounting,
    LeanCalls,
    ProofRuntime,
    TaskExecution,
)
from ai4algebra.verification import Verifier

_ROOT = Path(__file__).resolve().parents[2]
_TASK = "group-inverse-identity"


class OfflineRuntime:
    def __init__(
        self,
        corpus: Corpus,
        root: Path,
        config: RunConfig,
        directory: RunDirectory,
        run_id: str,
    ) -> None:
        assert (
            root == _ROOT
            and not config.paid_enabled
            and config.provider == "deterministic"
        )
        self.corpus = corpus
        self.config = config

    def search(
        self,
        problem: Problem,
        *,
        mode: SearchMode,
        options: SearchOptions,
        episode_id: str,
        policy: ActionPolicy | None = None,
    ) -> TaskExecution:
        report = SearchReport(
            problem=problem,
            policy_digest=self.corpus.policy_digest,
            eligibility_digest=self.corpus.eligibility_policy(
                problem
            ).eligibility_digest,
            policy_name="deterministic",
            mode=mode,
            episode_id=episode_id,
            limits=self.config.limits,
            options=options,
            verification_reserve_seconds=10.0,
            continuation_reserve_seconds=0.0,
            status="budget_exhausted",
            reason="steps",
            budget_reasons=("steps",),
            work=Work(),
            nodes=(),
            generations=(),
            attempts=(),
            last_observation=None,
            final_candidate_set=None,
        )
        return TaskExecution(report, LeanCalls())

    def api_accounting(self) -> ApiAccounting:
        return ApiAccounting()


def test_corpus_check_writes_public_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "corpus-check",
                "--offline",
                "--dotenv",
                str(tmp_path / "absent.env"),
                "--project-root",
                str(_ROOT),
                "--output",
                str(tmp_path),
            ]
        )
        == 0
    )
    catalog = CatalogIdentity.from_json((tmp_path / "corpus.json").read_bytes())
    assert catalog.corpus_id == "elementary" and len(catalog.tasks) == 4
    assert all(task.eligibility_digest is not None for task in catalog.tasks)
    assert "4 validated statements" in capsys.readouterr().out


def test_cli_offline_overrides_provider_environment_and_records_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("ai4algebra.cli.ProofRuntime", OfflineRuntime)
    env = tmp_path / "live.env"
    env.write_text(
        "AI4ALGEBRA_LLM_PROVIDER=openai\nAI4ALGEBRA_ALLOW_PAID_API=true\nOPENAI_API_KEY=local-secret-canary\n",
        encoding="utf-8",
    )
    output = tmp_path / "solve"
    assert (
        main(
            [
                "solve",
                "--project-root",
                str(_ROOT),
                "--task",
                _TASK,
                "--dotenv",
                str(env),
                "--offline",
                "--output",
                str(output),
                "--max-steps",
                "3",
            ]
        )
        == 1
    )
    trace = SearchReport.from_json((output / "result/search.json").read_bytes())
    assert trace.limits.max_steps == 3
    assert trace.status == "budget_exhausted"
    assert b"local-secret-canary" not in (output / "run.json").read_bytes()
    assert not (output / "provider-budget.sqlite").exists()
    assert "budget_exhausted" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("encoding", "expected_inverse"),
    [("cp1252", r"\u207b¹"), ("utf-8", "⁻¹")],
)
def test_cli_completes_unicode_solve_before_printing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    encoding: str,
    expected_inverse: str,
) -> None:
    output = tmp_path / "solve"
    api = ApiAccounting(budget_usd="0.50", settled_usd="0.01", reserved_requests=1)

    class VerifiedRuntime(OfflineRuntime):
        def search(
            self,
            problem: Problem,
            *,
            mode: SearchMode,
            options: SearchOptions,
            episode_id: str,
            policy: ActionPolicy | None = None,
        ) -> TaskExecution:
            execution = super().search(
                problem,
                mode=mode,
                options=options,
                episode_id=episode_id,
                policy=policy,
            )
            steps = (
                Candidate(
                    operation="simp_only",
                    goal_id="g0",
                    simp_lemmas=("mul_inv_cancel", "mul_one"),
                ),
            )
            certificate = Verifier(_ROOT).build_certificate(
                problem, steps, self.corpus.eligibility_policy(problem)
            )
            verdict = Verdict(
                status="accepted",
                replay_passed=True,
                type_passed=True,
                axioms_passed=True,
                dependencies_passed=True,
                lean_version="fixture",
                mathlib_revision="fixture",
                certificate_digest=digest_json(certificate.model_dump(mode="json")),
            )
            report = SearchReport.model_validate(
                execution.report.model_dump()
                | dict(
                    status="verified",
                    reason="closed",
                    budget_reasons=(),
                    certificate=certificate,
                    verdict=verdict,
                )
            )
            return TaskExecution(report, LeanCalls(verifier_requests=1))

        def api_accounting(self) -> ApiAccounting:
            return api

    class SolveOutput(TextIOWrapper):
        def write(self, text: str, /) -> int:
            assert (output / "solve.json").is_file()
            return super().write(text)

    monkeypatch.setattr("ai4algebra.cli.ProofRuntime", VerifiedRuntime)
    buffer = BytesIO()
    with SolveOutput(buffer, encoding=encoding, errors="strict") as console:
        with monkeypatch.context() as patch:
            patch.setattr("sys.stdout", console)
            assert (
                main(
                    [
                        "solve",
                        "--offline",
                        "--dotenv",
                        str(tmp_path / "absent.env"),
                        "--project-root",
                        str(_ROOT),
                        "--task",
                        _TASK,
                        "--output",
                        str(output),
                    ]
                )
                == 0
            )
        console.flush()
        lines = buffer.getvalue().decode(encoding).splitlines()
    assert lines[0] == f"Goal  a * (b * b{expected_inverse}) = a"
    assert lines[2].startswith("Verified proof at ")

    result = _SolveResult.from_json((output / "solve.json").read_bytes())
    assert result.status == "verified" and result.lean_calls.verifier_requests == 1
    assert result.api == api
    assert result.files is not None and result.files.proof is not None
    certificate = Certificate.from_json(
        (output / result.files.proof.certificate.path).read_bytes()
    )
    proof = (output / result.files.proof.proof.path).read_bytes()
    assert "b⁻¹".encode("utf-8") in proof
    assert proof.decode("utf-8") == certificate.proof


def test_cli_live_config_missing_key_fails_before_writing_or_dispatching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("AI4ALGEBRA_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AI4ALGEBRA_ALLOW_PAID_API", "true")
    monkeypatch.setenv("AI4ALGEBRA_API_BUDGET_USD", "0.50")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    output = tmp_path / "solve"
    assert (
        main(
            [
                "solve",
                "--project-root",
                str(_ROOT),
                "--task",
                _TASK,
                "--dotenv",
                str(tmp_path / "absent.env"),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert "OPENAI_API_KEY is required" in capsys.readouterr().err
    assert not output.exists()


def test_cli_rejects_held_out_training_task(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "wrong"
    assert (
        main(
            [
                "train",
                "--project-root",
                str(_ROOT),
                "--offline",
                "--dotenv",
                str(tmp_path / "absent.env"),
                "--task",
                "ring-add-cancel-pair",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert "validated train-split tasks" in capsys.readouterr().err
    assert not output.exists()


def test_concurrent_run_plan_first_writer_keeps_its_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = RunDirectory(tmp_path / "run")
    writers = Barrier(2)
    original = RunDirectory.put

    def delayed_put(
        directory: RunDirectory, name: str, value: Record | str
    ) -> ArtifactRef:
        time.sleep(0.05)
        return original(directory, name, value)

    def start(probes: int) -> tuple[int, str]:
        writers.wait(timeout=2.0)
        try:
            directory.plan(SearchOptions(probes_per_node=probes))
        except ValueError as exc:
            return probes, str(exc)
        return probes, "installed"

    monkeypatch.setattr(RunDirectory, "put", delayed_put)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = dict(executor.map(start, (1, 2)))
    saved = SearchOptions.from_json(directory.path("run.json").read_bytes())
    assert saved.probes_per_node is not None
    assert results[saved.probes_per_node] == "installed"
    assert (
        results[3 - saved.probes_per_node]
        == "output already belongs to a different run plan"
    )
    assert not directory.path(".run-plan.lock").exists()


def test_paid_accounting_preflight_does_not_create_a_ledger(tmp_path: Path) -> None:
    config = load_config(
        environ={
            "AI4ALGEBRA_LLM_PROVIDER": "openai",
            "AI4ALGEBRA_ALLOW_PAID_API": "true",
            "OPENAI_API_KEY": "local-only-fake",
        },
        dotenv_path=tmp_path / "absent.env",
    )
    directory = RunDirectory(tmp_path / "unused")
    runtime = ProofRuntime(
        Corpus.open(_ROOT / "data/manifests/elementary.json"),
        _ROOT,
        config,
        directory,
        "preflight",
    )
    stats = runtime.api_accounting()
    assert stats.budget_usd == "0.50" and stats.reserved_requests == 0
    assert not directory.root.exists()


def test_git_revision_lookup_excludes_provider_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key-canary")

    def git(
        command: tuple[str, ...],
        *,
        cwd: Path,
        capture_output: bool,
        check: bool,
        timeout: float,
        text: bool,
        env: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        assert "OPENAI_API_KEY" not in env and "ambient-key-canary" not in env.values()
        return subprocess.CompletedProcess(command, 0, "source-revision\n", "")

    monkeypatch.setattr("ai4algebra.training._artifacts.subprocess.run", git)
    assert _revision(_ROOT) == "source-revision"
