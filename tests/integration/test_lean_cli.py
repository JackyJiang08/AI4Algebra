"""Offline command-line proof export and independent replay on pinned Lean."""

import json
from pathlib import Path

import pytest

from ai4algebra.cli import main
from ai4algebra.contracts import Certificate, Verdict
from ai4algebra.search import SearchReport

pytestmark = pytest.mark.lean
_ROOT = Path(__file__).resolve().parents[2]


def test_cli_exports_standalone_proof_and_replays_its_certificate(
    tmp_path: Path,
) -> None:
    solve_dir = tmp_path / "solve"
    dotenv = str(tmp_path / "absent.env")
    assert (
        main(
            [
                "solve",
                "--project-root",
                str(_ROOT),
                "--offline",
                "--dotenv",
                dotenv,
                "--task",
                "group-inverse-identity",
                "--output",
                str(solve_dir),
                "--probes-per-node",
                "1",
                "--max-steps",
                "2",
                "--task-timeout-seconds",
                "300",
            ]
        )
        == 0
    )
    result = json.loads((solve_dir / "solve.json").read_bytes())
    proof_dir = solve_dir / "result"
    certificate = Certificate.from_json((proof_dir / "certificate.json").read_bytes())
    trace = SearchReport.from_json((proof_dir / "search.json").read_bytes())
    assert trace.certificate == certificate
    assert (proof_dir / "proof.lean").read_text(encoding="utf-8") == certificate.proof
    assert result["lean_calls"]["observer_requests"] == 3
    assert result["lean_calls"]["verifier_requests"] == 1
    assert (
        Path(result["files"]["proof"]["lean_replay_command"][-1])
        == proof_dir / "proof.lean"
    )
    command = result["replay_command"]
    assert command[:3] == ["python", "-m", "ai4algebra"]
    assert main([*command[3:], "--dotenv", dotenv]) == 0
    verdict = Verdict.from_json((solve_dir / "recheck/verdict.json").read_bytes())
    assert verdict.status == "accepted" and verdict.replay_passed
