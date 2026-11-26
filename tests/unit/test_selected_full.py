"""Full-system admission and explicit computational action boundaries."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ai4algebra import selected_full
from ai4algebra.candidates import DeterministicProposer, LemmaRule, ProposalRequest
from ai4algebra.config import Limits
from ai4algebra.contracts import Candidate, Goal
from ai4algebra.representation import EncoderConfig
from ai4algebra.selected_benchmark import CaseFile
from ai4algebra.selected_full import PREMISES, problems_and_policies

ROOT = Path(__file__).resolve().parents[2]


def test_target_and_exclusions_are_preserved_and_bootstrap_is_distinct() -> None:
    tasks, policies = problems_and_policies(ROOT)
    case = CaseFile.from_json(
        (ROOT / "data/selected/group_cases.json").read_bytes()
    ).cases[0]
    assert tasks[1].lean_statement == case.conclusion
    assert tasks[1].imports == case.imports
    assert tasks[0].statement_digest != tasks[1].statement_digest
    assert tasks[0].family_id == tasks[1].family_id
    assert (
        tasks[0].informal_statement
        == (ROOT / tasks[0].source.location).read_text().strip()
    )
    assert policies[0].policy_digest == policies[1].policy_digest
    for problem, policy in zip(tasks, policies, strict=True):
        policy.validate_for(problem, ())
        assert set(case.forbidden_declarations) <= set(policy.forbidden_declarations)
        assert case.reference_declaration in policy.forbidden_declarations
        assert policy.allowed_declarations == PREMISES
        assert "AI4Algebra.Benchmarks.Gold" in policy.forbidden_imports


def test_computational_templates_are_explicitly_opt_in() -> None:
    goal = Goal(
        goal_id="g0", target="True", expression='["const","True",[]]', hypotheses=()
    )
    request = ProposalRequest(statement="True", goals=(goal,), premises=())
    default = DeterministicProposer().propose(request, Limits())
    richer = DeterministicProposer(computational=True).propose(request, Limits())
    assert all(c.operation != "decide" for c in default.candidates)
    assert any(c.operation == "decide" for c in richer.candidates)
    assert richer.candidates[0].operation == "decide"
    assert set(default.candidates) <= set(richer.candidates)


@pytest.mark.parametrize(
    "operand",
    [
        {"lemma": "True.intro"},
        {"simp_lemmas": ("True.intro",)},
        {"direction": "backward"},
    ],
)
def test_decide_cannot_smuggle_an_operand(operand: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Candidate.model_validate({"operation": "decide", "goal_id": "g0", **operand})


def test_old_encoder_is_explicitly_incompatible() -> None:
    with pytest.raises(ValidationError):
        EncoderConfig(version="hashed-lean-v1")  # type: ignore[arg-type]


def test_kernel_private_names_are_evidence_not_tactic_operands() -> None:
    name = "_private.Init.Prelude.0.Nat.zero_le.match_1_1"
    rule = LemmaRule(
        name="True.intro",
        statement="True",
        expression='["const","True",[]]',
        module="Init.Prelude",
        dependencies=(name,),
    )
    assert LemmaRule.from_json(rule.to_json()).dependencies == (name,)
    with pytest.raises(ValidationError):
        Candidate(operation="exact", goal_id="g0", lemma=name)


def test_exclusive_run_claim_preserves_previous_error_and_redacts_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(
        root: Path, output: Path, *, offline: bool, budget_run: Path | None = None
    ) -> dict[str, object]:
        raise RuntimeError("sensitive-exception-payload")

    monkeypatch.setattr(selected_full, "_run_owned", fail)
    output = tmp_path / "runs/unique-run"
    with pytest.raises(RuntimeError):
        selected_full.run(tmp_path, output, offline=True)
    summary = (output / "summary.json").read_bytes()
    assert b"RuntimeError" in summary
    assert b"sensitive-exception-payload" not in summary
    with pytest.raises(FileExistsError):
        selected_full.run(tmp_path, output, offline=True)
    with pytest.raises(FileExistsError):
        selected_full.run(tmp_path, tmp_path / "different/unique-run", offline=True)
    assert (output / "summary.json").read_bytes() == summary
