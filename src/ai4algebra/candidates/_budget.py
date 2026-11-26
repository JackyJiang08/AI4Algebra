"""Durable per-run reservations for bounded text-only Responses requests."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from ai4algebra.config import MAX_API_BUDGET_USD
from ai4algebra.contracts import Identifier, digest_json

_RUN_ID = TypeAdapter[Identifier](Identifier)
_NANOS_PER_DOLLAR = 1_000_000_000


@dataclass(frozen=True)
class PriceSchedule:
    model: str
    tier: str
    revision: str
    uncached_input_nanos: int
    cached_input_nanos: int
    output_nanos: int
    max_input_tokens: int
    max_output_tokens: int

    @property
    def digest(self) -> str:
        return digest_json(vars(self))


# Official Standard price snapshot (2026-11-25): short-context, global endpoint.
# https://developers.openai.com/api/docs/models/gpt-6.2-astra
ASTRA_STANDARD = PriceSchedule(
    model="gpt-6.2-astra",
    tier="default",
    revision="openai-text-standard-2026-11-25",
    uncached_input_nanos=8_000,
    cached_input_nanos=400,
    output_nanos=40_000,
    max_input_tokens=272_000,
    max_output_tokens=128_000,
)


class BudgetError(RuntimeError):
    """A budget ledger identity or accounting invariant failed."""


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    input_tokens: int
    max_output_tokens: int
    reserved_nanos: int


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cache_write_tokens: int


@dataclass(frozen=True)
class BudgetSummary:
    budget_usd: Decimal
    spent_usd: Decimal
    outstanding_usd: Decimal
    requests: int
    unresolved: int
    blocked: bool
    price_digest: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


def _usd(nanos: int) -> Decimal:
    return Decimal(nanos) / Decimal(_NANOS_PER_DOLLAR)


class BudgetLedger:
    """One SQLite file shared by every worker and restart of a single run."""

    def __init__(
        self, path: str | Path, run_id: str, budget_usd: Decimal, *, create: bool = True
    ) -> None:
        if (
            not isinstance(budget_usd, Decimal)
            or not budget_usd.is_finite()
            or not 0 <= budget_usd <= MAX_API_BUDGET_USD
        ):
            raise BudgetError(
                f"API budget must be between USD 0 and USD {MAX_API_BUDGET_USD}"
            )
        numerator, denominator = budget_usd.as_integer_ratio()
        self._limit = numerator * _NANOS_PER_DOLLAR // denominator
        self._run_id = _RUN_ID.validate_python(run_id, strict=True)
        self._path = Path(path).resolve()
        identity = (1, self._run_id, ASTRA_STANDARD.digest, self._limit)
        try:
            with closing(self._connect(create=create)) as db, db:
                db.execute("BEGIN IMMEDIATE" if create else "BEGIN")
                if create:
                    db.execute("""
                CREATE TABLE IF NOT EXISTS run (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    version INTEGER NOT NULL, run_id TEXT NOT NULL,
                    price_digest TEXT NOT NULL, budget INTEGER NOT NULL,
                    blocked INTEGER NOT NULL DEFAULT 0 CHECK (blocked IN (0, 1))
                )
                """)
                    db.execute("""
                CREATE TABLE IF NOT EXISTS reservations (
                    id TEXT PRIMARY KEY, input_bound INTEGER NOT NULL,
                    output_bound INTEGER NOT NULL, reserved INTEGER NOT NULL,
                    actual INTEGER, input_used INTEGER, output_used INTEGER,
                    cached_used INTEGER
                )
                """)
                    db.execute(
                        "INSERT OR IGNORE INTO run VALUES (1, ?, ?, ?, ?, 0)", identity
                    )
                installed = db.execute(
                    "SELECT version, run_id, price_digest, budget FROM run WHERE singleton = 1"
                ).fetchone()
                if installed != identity:
                    raise BudgetError(
                        "budget ledger version, run, prices or budget do not match"
                    )
                db.execute(
                    "SELECT id, input_bound, output_bound, reserved, actual, input_used, output_used, cached_used FROM reservations LIMIT 0"
                )
        except sqlite3.Error:
            raise BudgetError("budget ledger is unavailable or malformed") from None

    @property
    def budget_usd(self) -> Decimal:
        return _usd(self._limit)

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        # Only explicit initialization may create a file. A lost retry ledger
        # must never silently reset charges or outstanding reservations.
        mode = "rwc" if create else "rw"
        try:
            return sqlite3.connect(
                f"{self._path.as_uri()}?mode={mode}", uri=True, timeout=2.0
            )
        except sqlite3.Error:
            raise BudgetError("budget ledger is unavailable") from None

    def reserve(self, input_tokens: int, max_output_tokens: int) -> Reservation | None:
        if (
            type(input_tokens) is not int
            or not 0 < input_tokens <= ASTRA_STANDARD.max_input_tokens
            or type(max_output_tokens) is not int
            or not 0 < max_output_tokens <= ASTRA_STANDARD.max_output_tokens
        ):
            raise BudgetError("request token bounds are outside the pinned schedule")
        amount = (
            input_tokens * ASTRA_STANDARD.uncached_input_nanos
            + max_output_tokens * ASTRA_STANDARD.output_nanos
        )
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            blocked = db.execute(
                "SELECT blocked FROM run WHERE singleton = 1"
            ).fetchone()[0]
            used = db.execute(
                "SELECT COALESCE(SUM(COALESCE(actual, reserved)), 0) FROM reservations"
            ).fetchone()[0]
            if blocked or used + amount > self._limit:
                return None
            reservation = Reservation(
                uuid4().hex, input_tokens, max_output_tokens, amount
            )
            db.execute(
                "INSERT INTO reservations (id, input_bound, output_bound, reserved) VALUES (?, ?, ?, ?)",
                (reservation.reservation_id, input_tokens, max_output_tokens, amount),
            )
            return reservation

    def settle(self, reservation: Reservation, usage: Usage) -> None:
        if (
            any(type(count) is not int for count in vars(usage).values())
            or not 0
            <= usage.cached_tokens
            <= usage.input_tokens
            <= reservation.input_tokens
            or not 0 <= usage.output_tokens <= reservation.max_output_tokens
            or usage.cache_write_tokens != 0
        ):
            self.block()
            raise BudgetError(
                "reported usage breached reserved token or caching bounds"
            )
        amount = (
            (usage.input_tokens - usage.cached_tokens)
            * ASTRA_STANDARD.uncached_input_nanos
            + usage.cached_tokens * ASTRA_STANDARD.cached_input_nanos
            + usage.output_tokens * ASTRA_STANDARD.output_nanos
        )
        with closing(self._connect()) as db, db:
            changed = db.execute(
                """
                UPDATE reservations SET actual = ?, input_used = ?, output_used = ?, cached_used = ?
                WHERE id = ? AND input_bound = ? AND output_bound = ? AND reserved = ?
                AND actual IS NULL
                """,
                (
                    amount,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.cached_tokens,
                    reservation.reservation_id,
                    reservation.input_tokens,
                    reservation.max_output_tokens,
                    reservation.reserved_nanos,
                ),
            )
            if changed.rowcount != 1:
                raise BudgetError("reservation identity is unknown or already settled")

    def block(self) -> None:
        """Keep all reservations and permanently stop new ones after a pricing mismatch."""
        with closing(self._connect()) as db, db:
            db.execute("UPDATE run SET blocked = 1 WHERE singleton = 1")

    def summary(self) -> BudgetSummary:
        with closing(self._connect()) as db, db:
            (
                blocked,
                spent,
                outstanding,
                requests,
                unresolved,
                inputs,
                outputs,
                cached,
            ) = db.execute(
                """
                SELECT blocked, COALESCE(SUM(actual), 0),
                    COALESCE(SUM(CASE WHEN actual IS NULL THEN reserved END), 0),
                    COUNT(reservations.id), COUNT(reservations.id) - COUNT(actual),
                    COALESCE(SUM(input_used), 0), COALESCE(SUM(output_used), 0),
                    COALESCE(SUM(cached_used), 0)
                FROM run LEFT JOIN reservations ON 1 = 1 WHERE singleton = 1
                """
            ).fetchone()
        return BudgetSummary(
            self.budget_usd,
            _usd(spent),
            _usd(outstanding),
            requests,
            unresolved,
            bool(blocked),
            ASTRA_STANDARD.digest,
            inputs,
            outputs,
            cached,
        )
