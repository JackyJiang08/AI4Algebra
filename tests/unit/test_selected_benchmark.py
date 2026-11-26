import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai4algebra import selected_benchmark as benchmark
from ai4algebra.config import Limits
from ai4algebra.contracts import (
    Candidate,
    Certificate,
    Goal,
    Observation,
    Problem,
    Snapshot,
    StepResult,
    Verdict,
    digest_json,
)
from ai4algebra.lean_bridge import BridgeError
from ai4algebra.lean_bridge.protocol import LEAN_VERSION, MATHLIB_REVISION
from ai4algebra.search import SearchReport
from ai4algebra.verification import EligibilityPolicy, render_proof

_ENVIRONMENT = digest_json("fixture environment")
_GOLD = "AI4Algebra.Benchmarks.Gold.Selected"
_FORBIDDEN = f"{_GOLD}.exercise16"


def _case(exercise: int, **fields: object) -> dict[str, object]:
    return {
        "id": f"exercise-{exercise}",
        "exercise": exercise,
        "title": f"Fixture {exercise}",
        "imports": ["Mathlib.Algebra.Group.Basic"],
        "universes": [],
        "binders": [],
        "conclusion": "True",
        "reference_declaration": f"{_GOLD}.exercise{exercise}",
        "reference_file": "AI4Algebra/Benchmarks/Gold/missing.lean",
        "reference_imports": [f"{_GOLD}.SomeReferenceOnlyModule"],
        "mapping_note": "Fixture for archive behavior.",
        "forbidden_declarations": [f"directAlias{exercise}"],
        "basic_premises": ["mul_assoc"],
        **fields,
    }


@pytest.mark.parametrize(
    "fields, message",
    [
        (
            {"imports": [f"{_GOLD}.SelectedGroups"]},
            "unapproved selected-exercise import",
        ),
        (
            {"imports": ["AI4Algebra.Benchmarks.Statements"]},
            "unapproved selected-exercise import",
        ),
        ({"reference_declaration": "unprotected"}, "protected Gold namespace"),
        ({"id": "../exercise-11"}, "String should match pattern"),
    ],
)
def test_case_file_rejects_unsafe_input(
    fields: dict[str, object], message: str
) -> None:
    content = json.dumps({"schema_version": 1, "cases": [_case(11, **fields)]})
    with pytest.raises(ValidationError, match=message):
        benchmark.CaseFile.from_json(content)


class _FixtureBridge:
    def __init__(self, root: Path, *, approved_imports: frozenset[str]) -> None:
        assert "Mathlib.Algebra.Group.Basic" in approved_imports
        assert not any(
            name.startswith("AI4Algebra.Benchmarks.Gold") for name in approved_imports
        )

    def open(self, problem: Problem, limits: Limits) -> tuple[Snapshot, Observation]:
        assert problem.split == "train"
        assert problem.imports == ("Mathlib.Algebra.Group.Basic",)
        if problem.task_id == "exercise-16":
            raise BridgeError("fixture initial elaboration error")
        snapshot = Snapshot(
            session_id="fixture-lean",
            environment_digest=_ENVIRONMENT,
            prefix_digest=digest_json(()),
            snapshot_id="root",
        )
        return snapshot, Observation(
            snapshot=snapshot,
            goals=(
                Goal(goal_id="g0", target="True", expression='["const","True",[]]'),
            ),
        )

    def fork(self, snapshot: Snapshot) -> Snapshot:
        return snapshot

    def step(self, snapshot: Snapshot, candidate: Candidate) -> StepResult:
        if candidate.operation != "constructor":
            return StepResult(
                status="rejected", diagnostics=("fixture: tactic failed",)
            )
        child = snapshot.model_copy(
            update={
                "prefix_digest": digest_json((candidate.candidate_id,)),
                "snapshot_id": "closed",
            }
        )
        return StepResult(
            status="closed",
            snapshot=child,
            observation=Observation(snapshot=child, goals=()),
        )

    def close(self, session_id: str) -> None:
        assert session_id == "fixture-lean"


class _FixtureVerifier:
    audit_passes = True

    def __init__(self, root: Path, *, timeout_seconds: float) -> None:
        assert timeout_seconds == 60.0

    def build_certificate(
        self,
        problem: Problem,
        steps: tuple[Candidate, ...],
        eligibility: EligibilityPolicy,
    ) -> Certificate:
        assert eligibility.allowed_declarations == ()
        assert _FORBIDDEN in eligibility.forbidden_declarations
        assert "directAlias16" in eligibility.forbidden_declarations
        assert eligibility.forbidden_imports == ("AI4Algebra.Benchmarks.Gold",)
        return Certificate(
            task_id=problem.task_id,
            statement_digest=problem.statement_digest,
            environment_digest=_ENVIRONMENT,
            source_digest=problem.source.content_digest,
            policy_digest=eligibility.policy_digest,
            eligibility_digest=eligibility.eligibility_digest,
            imports=problem.imports,
            steps=steps,
            proof=render_proof(problem, steps),
        )

    def verify(
        self,
        problem: Problem,
        certificate: Certificate,
        eligibility: EligibilityPolicy,
        *,
        timeout_seconds: float,
    ) -> Verdict:
        assert timeout_seconds > 0
        return Verdict(
            status="accepted" if self.audit_passes else "rejected",
            replay_passed=True,
            type_passed=True,
            axioms_passed=True,
            dependencies_passed=self.audit_passes,
            certificate_digest=digest_json(certificate.model_dump(mode="json")),
            lean_version=LEAN_VERSION,
            mathlib_revision=MATHLIB_REVISION,
        )


@pytest.mark.parametrize("audit_passes", [True, False])
def test_offline_run_archives_each_result_and_preserves_existing_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, audit_passes: bool
) -> None:
    source = tmp_path / "data/training_questions.md"
    source.parent.mkdir()
    source.write_text(
        "## 1. Exercise 11\n\nFirst problem.\n\n**Value:** Its purpose.\n\n"
        "## 2. Exercise 16\n\nSecond problem.\n",
        encoding="utf-8",
    )
    for name in ("lean-toolchain", "lakefile.toml", "lake-manifest.json"):
        (tmp_path / name).touch()
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps({"schema_version": 1, "cases": [_case(16), _case(11)]}),
        encoding="utf-8",
    )
    output = tmp_path / "run"
    records = tmp_path / "records"

    def unexpected_settings(*args: object, **kwargs: object) -> None:
        pytest.fail("the structural baseline must not load provider settings")

    monkeypatch.setenv("AI4ALGEBRA_LLM_PROVIDER", "openai")
    monkeypatch.setenv("AI4ALGEBRA_ALLOW_PAID_API", "true")
    monkeypatch.setattr("ai4algebra.config.dotenv_values", unexpected_settings)
    monkeypatch.setattr("ai4algebra.config.load_config", unexpected_settings)
    monkeypatch.setattr(benchmark, "LeanBridge", _FixtureBridge)
    monkeypatch.setattr(_FixtureVerifier, "audit_passes", audit_passes)
    monkeypatch.setattr(benchmark, "Verifier", _FixtureVerifier)

    result = benchmark.run_selected(
        tmp_path, output, records, [cases], run_id="fixture-1"
    )
    expected = "verified" if audit_passes else "verification_rejected"
    assert result["status_counts"] == {expected: 1, "infrastructure_error": 1}
    assert result["initial_observation_failures"] == 1
    assert result["task_ids"] == ["exercise-11", "exercise-16"]
    assert result["reference_proof_mode"] == "not_executed_by_this_runner"
    assert result["case_files"] == {
        cases.as_posix(): hashlib.sha256(cases.read_bytes()).hexdigest()
    }
    assert json.loads((output / "summary.json").read_bytes())["completed"]
    case_branch = "succeeded" if audit_passes else "failed"
    closed = records / case_branch / "fixture-1/exercise-11/attempt-001"
    failed = records / "failed/fixture-1/exercise-16/attempt-001"
    assert (closed / "proof.lean").is_file() == audit_passes
    assert (closed / "certificate.json").is_file() == audit_passes
    trace = SearchReport.from_json((closed / "search.json").read_bytes())
    audit = trace.attempts[0].verdict
    assert audit is not None
    assert audit.status == ("accepted" if audit_passes else "rejected")
    assert trace.work.provider_requests == trace.work.token_count_requests == 0
    assert not trace.transitions and not trace.samples
    assert "First problem.\n\n**Value:** Its purpose." in (
        closed / "problem.md"
    ).read_text(encoding="utf-8")
    assert "fixture initial elaboration error" in (failed / "outcome.md").read_text(
        encoding="utf-8"
    )
    assert (failed / "attempted-steps.json").is_file()
    assert not (failed / "proof.lean").exists()
    assert "sorry" not in (failed / "statement.lean").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError, match="attempts already exist"):
        benchmark.run_selected(
            tmp_path, tmp_path / "retry", records, [cases], run_id="fixture-1"
        )
    (records / ".locks/claimed").mkdir()
    with pytest.raises(FileExistsError, match="run ID already claimed"):
        benchmark.run_selected(
            tmp_path, tmp_path / "another-output", records, [cases], run_id="claimed"
        )


def test_cli_requires_reviewed_case_file_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit, match="2"):
        benchmark.main(
            [
                "--output",
                str(tmp_path / "run"),
                "--case-file",
                str(tmp_path / "foreign.json"),
            ]
        )
    assert "select both reviewed case files" in capsys.readouterr().err
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize(
    "error_type, reason",
    [(KeyboardInterrupt, "interrupted"), (BridgeError, "execution_failed")],
)
def test_missing_trace_preserves_unknown_observation_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
    reason: str,
) -> None:
    source = tmp_path / "data/training_questions.md"
    source.parent.mkdir()
    source.write_text("## 1. Exercise 11\n\nFixture statement.\n", encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps({"schema_version": 1, "cases": [_case(11)]}), encoding="utf-8"
    )
    for name in ("lean-toolchain", "lakefile.toml", "lake-manifest.json"):
        (tmp_path / name).touch()

    def unavailable(*args: object) -> SearchReport:
        raise error_type("fixture no-trace exception")

    monkeypatch.setattr(benchmark, "_search", unavailable)
    output = tmp_path / "run"
    records = tmp_path / "records"
    if error_type is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt):
            benchmark.run_selected(tmp_path, output, records, [cases])
    else:
        benchmark.run_selected(tmp_path, output, records, [cases])

    summary = json.loads((output / "summary.json").read_bytes())
    assert summary["attempted_count"] == 1
    assert summary["initial_observation_failures"] == 0
    assert summary["results"][0]["reason"] == reason
    assert summary["results"][0]["initial_goal_observed"] is None
    assert summary["results"][0]["failure_phase"] == "unknown"
    archived = records / "failed/run/exercise-11/attempt-001"
    assert not (archived / "search.json").exists()
    steps = json.loads((archived / "attempted-steps.json").read_bytes())
    assert steps["selected_actions"] is None
    assert steps["applicability_probes"] is None
    assert "Initial Lean goal observed: unknown." in (
        archived / "outcome.md"
    ).read_text(encoding="utf-8")
