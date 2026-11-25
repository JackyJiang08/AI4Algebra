"""Exercise typed proof search through the pinned observer and independent audit."""

from pathlib import Path

import pytest

from ai4algebra.candidates import CandidateGenerator, elementary_premise_index
from ai4algebra.config import Limits
from ai4algebra.corpus import Corpus
from ai4algebra.lean_bridge import LeanBridge
from ai4algebra.search import SearchOptions, SearchReport, solve
from ai4algebra.verification import Verifier

pytestmark = pytest.mark.lean
_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / "data/manifests/elementary.json"


def _search(max_steps: int) -> SearchReport:
    corpus = Corpus.open(_MANIFEST)
    problem = next(
        p for p in corpus.problems() if p.task_id == "group-inverse-identity"
    )
    eligibility = corpus.allowed_declarations(problem.task_id)
    bridge = LeanBridge(_ROOT)
    generator = CandidateGenerator(
        problem,
        eligibility,
        bridge,
        premise_index=elementary_premise_index(corpus, problem, _ROOT),
    )
    return solve(
        problem,
        eligibility,
        bridge,
        generator,
        Verifier(_ROOT, timeout_seconds=120.0),
        Limits(
            max_candidates=8,
            max_steps=max_steps,
            step_timeout_seconds=120.0,
            task_timeout_seconds=450.0,
        ),
        mode="best_first",
        episode_id=f"lean-smoke-{max_steps}",
        options=SearchOptions(
            probes_per_node=1, verification_reserve_seconds=120.0, stop_on_closure=True
        ),
    )


def test_real_elementary_multistep_search_exports_verified_artifacts(
    tmp_path: Path,
) -> None:
    report = _search(max_steps=2)
    assert report.status == "verified", (
        report.budget_reasons,
        report.attempts,
        report.diagnostics,
    )
    certificate = report.certificate
    assert certificate is not None and report.verdict is not None
    assert report.verdict.status == "accepted"
    assert len(certificate.steps) == 2
    assert tuple(attempt.outcome for attempt in report.attempts) == (
        "advanced",
        "verified",
    )
    assert report.work.step_calls == 2
    assert report.work.action_calls == 0 and report.work.reused_probes == 2
    assert report.work.verifier_calls == 1
    assert report.generations[-1].stopped_after_closure
    assert report.last_observation is not None and not report.last_observation.goals
    assert report.nodes[-1].statement_digest == report.problem.statement_digest

    (tmp_path / "proof.lean").write_text(certificate.proof, encoding="utf-8")
    (tmp_path / "certificate.json").write_text(certificate.to_json(), encoding="utf-8")
    (tmp_path / "verdict.json").write_text(report.verdict.to_json(), encoding="utf-8")
    trace = tmp_path / "search.json"
    trace.write_text(report.to_json(), encoding="utf-8")
    assert SearchReport.from_json(trace.read_bytes()) == report


def test_real_elementary_search_keeps_unsolved_observation_at_budget() -> None:
    report = _search(max_steps=1)
    assert report.status == "budget_exhausted", report.diagnostics
    assert report.reason == "steps"
    assert report.certificate is None and report.verdict is None
    assert report.work.step_calls == 1 and report.work.verifier_calls == 0
    assert report.last_observation is not None and report.last_observation.goals
    assert report.last_observation == report.nodes[-1].observation
