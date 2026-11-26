"""A retry must reuse real durable charges, never silently recreate its ledger."""

from decimal import Decimal
from pathlib import Path

import pytest

from ai4algebra.candidates import BudgetError, BudgetLedger
from ai4algebra.candidates._budget import Usage


def test_reuse_rejects_missing_and_empty_ledgers_without_creation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "budget.sqlite"
    with pytest.raises(BudgetError):
        BudgetLedger(path, "run", Decimal("0.50"), create=False)
    assert not path.exists()
    path.write_bytes(b"")
    with pytest.raises(BudgetError):
        BudgetLedger(path, "run", Decimal("0.50"), create=False)
    assert path.read_bytes() == b""


def test_reuse_preserves_settled_and_outstanding_costs_and_identity(
    tmp_path: Path,
) -> None:
    path = tmp_path / "budget.sqlite"
    original = BudgetLedger(path, "run", Decimal("0.50"))
    settled = original.reserve(100, 64)
    assert settled is not None
    original.settle(settled, Usage(100, 30, 0, 0))
    assert original.reserve(100, 64) is not None
    before = original.summary()
    data = path.read_bytes()
    reused = BudgetLedger(path, "run", Decimal("0.50"), create=False)
    assert reused.summary() == before
    assert before.spent_usd > 0 and before.outstanding_usd > 0
    assert path.read_bytes() == data
    for run_id, budget in (("wrong-run", Decimal("0.50")), ("run", Decimal("0.49"))):
        with pytest.raises(BudgetError):
            BudgetLedger(path, run_id, budget, create=False)
    assert path.read_bytes() == data


def test_later_connections_cannot_recreate_a_disappeared_ledger(tmp_path: Path) -> None:
    path = tmp_path / "budget.sqlite"
    BudgetLedger(path, "run", Decimal("0.50"))
    reused = BudgetLedger(path, "run", Decimal("0.50"), create=False)
    path.unlink()
    with pytest.raises(BudgetError):
        reused.summary()
    with pytest.raises(BudgetError):
        reused.reserve(100, 64)
    assert not path.exists()
