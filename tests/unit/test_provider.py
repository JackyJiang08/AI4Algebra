"""OpenAI request policy and durable accounting using mock HTTPS responses."""

import json
import pickle
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from threading import Barrier, Event

import pytest
from pydantic import SecretStr

from ai4algebra.candidates import (
    ASTRA_STANDARD,
    BudgetError,
    BudgetLedger,
    Endpoint,
    HttpResponse,
    OpenAIProposer,
    ProposalRequest,
    TransportError,
)
from ai4algebra.candidates._budget import Usage
from ai4algebra.candidates._http import OpenAIHTTPS
from ai4algebra.config import Limits, RunConfig, load_config
from ai4algebra.contracts import Goal

_KEY = "redaction-sentinel-key"
_VIEW = ProposalRequest(
    statement="True",
    goals=(Goal(goal_id="g0", target="True", expression='["const","True",[]]'),),
    premises=(),
)
_LIMITS = Limits(max_output_tokens=64)
_RESERVED = Decimal("0.00336")
_ACTUAL = Decimal("0.002")


def _body(value: object, status: int = 200) -> HttpResponse:
    return HttpResponse(status, json.dumps(value).encode())


def _count(tokens: int = 100) -> HttpResponse:
    return _body({"object": "response.input_tokens", "input_tokens": tokens})


def _candidate(**changes: object) -> dict[str, object]:
    return {
        "operation": "constructor",
        "goal_id": "g0",
        "lemma": None,
        "local_id": None,
        "arguments": [],
        "direction": "forward",
        "location": None,
        "simp_lemmas": [],
    } | changes


def _generation(
    output: object | None = None,
    *,
    output_tokens: int = 30,
    tier: str = "default",
    cache_writes: int = 0,
    status: str = "completed",
) -> HttpResponse:
    text = (
        json.dumps({"candidates": [_candidate()]})
        if output is None
        else json.dumps(output)
    )
    return _body(
        {
            "object": "response",
            "model": "gpt-6.2-astra",
            "service_tier": tier,
            "status": status,
            "tools": [],
            "background": False,
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {
                    "cached_tokens": 0,
                    "cache_write_tokens": cache_writes,
                },
                "output_tokens": output_tokens,
                "output_tokens_details": {"reasoning_tokens": 24},
                "total_tokens": 100 + output_tokens,
            },
            "output": [
                {"type": "reasoning"},
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text}],
                },
            ],
        }
    )


def _config(tmp_path: Path, budget: str) -> RunConfig:
    return load_config(
        environ={
            "AI4ALGEBRA_LLM_PROVIDER": "openai",
            "AI4ALGEBRA_ALLOW_PAID_API": "true",
            "OPENAI_API_KEY": _KEY,
            "AI4ALGEBRA_API_BUDGET_USD": budget,
        },
        dotenv_path=tmp_path / "nonexistent.env",
    )


@dataclass
class MockTransport:
    ledger: BudgetLedger
    responses: list[HttpResponse | TransportError]
    calls: list[tuple[Endpoint, dict[str, object]]] = field(default_factory=list)

    def post(
        self,
        endpoint: Endpoint,
        payload: bytes,
        *,
        key: SecretStr,
        timeout_seconds: float,
        cancelled: Event | None,
    ) -> HttpResponse:
        assert key.get_secret_value() == _KEY
        assert _KEY.encode() not in payload
        assert timeout_seconds > 0
        if endpoint == "/responses":
            assert self.ledger.summary().outstanding_usd >= _RESERVED
        self.calls.append((endpoint, json.loads(payload)))
        response = self.responses.pop(0)
        if isinstance(response, TransportError):
            raise response
        return response


def test_full_request_is_counted_before_reservation_and_billed_reasoning_is_settled(
    tmp_path: Path,
) -> None:
    ledger = BudgetLedger(tmp_path / "budget.db", "run", Decimal("0.01"))
    transport = MockTransport(ledger, [_count(), _generation()])
    result = OpenAIProposer(_config(tmp_path, "0.01"), ledger, transport).propose(
        _VIEW, _LIMITS
    )
    assert result.status == "ok" and result.requests == result.token_count_requests == 1
    assert (
        len(result.candidates) == 1 and result.candidates[0].operation == "constructor"
    )
    (count_path, count), (generation_path, generation) = transport.calls
    assert count_path == "/responses/input_tokens" and generation_path == "/responses"
    assert {key: generation[key] for key in count} == count
    assert generation["model"] == ASTRA_STANDARD.model
    assert generation["reasoning"] == {"effort": "high"}
    assert generation["tools"] == [] and generation["tool_choice"] == "none"
    assert (
        generation["truncation"] == "disabled"
        and generation["service_tier"] == "default"
    )
    assert generation["max_output_tokens"] == 64
    assert generation["prompt_cache_options"] == {"mode": "explicit", "prewarm": False}
    assert (
        generation["background"] is generation["stream"] is generation["store"] is False
    )
    assert ledger.summary().spent_usd == _ACTUAL
    assert (
        ledger.summary().input_tokens,
        ledger.summary().output_tokens,
        ledger.summary().cached_tokens,
    ) == (100, 30, 0)
    assert ledger.summary().outstanding_usd == 0
    assert _KEY not in repr(result)
    assert _KEY.encode() not in (tmp_path / "budget.db").read_bytes()


def test_retry_timeout_keeps_uncertain_reservation_across_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "budget.db"
    ledger = BudgetLedger(path, "run", Decimal("0.007"))
    config = _config(tmp_path, "0.007")
    transport = MockTransport(
        ledger, [_count(), TransportError("timeout"), _generation()]
    )
    result = OpenAIProposer(config, ledger, transport).propose(_VIEW, _LIMITS)
    assert result.status == "ok" and result.requests == 2
    assert [route for route, _ in transport.calls] == [
        "/responses/input_tokens",
        "/responses",
        "/responses",
    ]

    resumed = BudgetLedger(path, "run", Decimal("0.007"))
    assert resumed.summary().spent_usd == _ACTUAL
    assert resumed.summary().outstanding_usd == _RESERVED
    assert resumed.summary().unresolved == 1
    assert (resumed.summary().input_tokens, resumed.summary().output_tokens) == (
        100,
        30,
    )
    second = MockTransport(resumed, [_count()])
    fallback = OpenAIProposer(config, resumed, second).propose(_VIEW, _LIMITS)
    assert fallback.status == "budget_exhausted" and fallback.requests == 0
    assert [route for route, _ in second.calls] == ["/responses/input_tokens"]
    assert resumed.summary().requests == 2


def test_concurrent_workers_share_one_unchanged_ceiling(tmp_path: Path) -> None:
    path = tmp_path / "budget.db"
    ceiling = Decimal("0.50")
    left = BudgetLedger(path, "run", ceiling)
    first = left.reserve(12_500, 3_750)
    assert first is not None
    left.settle(first, Usage(12_500, 3_750, 0, 0))

    right = BudgetLedger(path, "run", ceiling)
    gate = Barrier(2)

    def reserve(ledger: BudgetLedger) -> bool:
        gate.wait(timeout=5)
        return ledger.reserve(12_500, 3_750) is not None

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(reserve, (left, right))) == [False, True]
    resumed = BudgetLedger(path, "run", ceiling)
    summary = resumed.summary()
    assert summary == left.summary() == right.summary()
    assert summary.spent_usd == summary.outstanding_usd == Decimal("0.25")
    assert summary.requests == 2 and summary.unresolved == 1
    assert resumed.reserve(1, 1) is None
    with pytest.raises(BudgetError, match="do not match"):
        BudgetLedger(path, "run", Decimal("0.49"))
    with pytest.raises(BudgetError, match="do not match"):
        BudgetLedger(path, "another", ceiling)


def test_ledger_rejects_budget_above_ceiling_before_rounding(tmp_path: Path) -> None:
    path = tmp_path / "budget.db"
    with pytest.raises(BudgetError, match=r"between USD 0 and USD 0\.50"):
        BudgetLedger(path, "run", Decimal("0.5000000000000000000000000000000000001"))
    assert not path.exists()


@pytest.mark.parametrize(
    "response",
    [
        _generation(tier="priority"),
        _generation(cache_writes=1),
        _generation(output_tokens=65),
    ],
)
def test_out_of_contract_pricing_keeps_reservation_and_blocks_run(
    tmp_path: Path, response: HttpResponse
) -> None:
    path = tmp_path / "budget.db"
    ledger = BudgetLedger(path, "run", Decimal("0.50"))
    config = _config(tmp_path, "0.50")
    transport = MockTransport(ledger, [_count(), response])
    result = OpenAIProposer(config, ledger, transport).propose(_VIEW, _LIMITS)
    assert result.status == "pricing_mismatch"
    restored = BudgetLedger(path, "run", Decimal("0.50"))
    assert (
        restored.summary().blocked and restored.summary().outstanding_usd == _RESERVED
    )
    assert restored.reserve(100, 64) is None


def test_malformed_or_incomplete_output_still_accounts_for_known_usage(
    tmp_path: Path,
) -> None:
    ledger = BudgetLedger(tmp_path / "budget.db", "run", Decimal("0.01"))
    responses: list[HttpResponse | TransportError] = [
        _count(),
        _generation({"candidates": [_candidate(operation="exact?; admit")]}),
        _count(),
        _generation(status="incomplete"),
    ]
    transport = MockTransport(ledger, responses)
    provider = OpenAIProposer(_config(tmp_path, "0.01"), ledger, transport)
    assert provider.propose(_VIEW, _LIMITS).status == "malformed"
    assert provider.propose(_VIEW, _LIMITS).status == "incomplete"
    assert ledger.summary().spent_usd == 2 * _ACTUAL
    assert ledger.summary().unresolved == 0


def test_disabled_cancelled_oversized_and_redirect_requests_never_generate(
    tmp_path: Path,
) -> None:
    ledger = BudgetLedger(tmp_path / "budget.db", "run", Decimal("0.01"))
    transport = MockTransport(ledger, [_count(4097), _body({"error": _KEY}, 307)])
    disabled = OpenAIProposer(RunConfig(), ledger, transport)
    assert disabled.propose(_VIEW, _LIMITS).status == "disabled"
    provider = OpenAIProposer(_config(tmp_path, "0.01"), ledger, transport)
    cancelled = Event()
    cancelled.set()
    assert provider.propose(_VIEW, _LIMITS, cancelled=cancelled).status == "cancelled"
    assert not transport.calls
    assert provider.propose(_VIEW, _LIMITS).status == "input_limit"
    unavailable = provider.propose(_VIEW, _LIMITS)
    assert unavailable.status == "unavailable" and _KEY not in repr(unavailable)
    assert [route for route, _ in transport.calls] == [
        "/responses/input_tokens",
        "/responses/input_tokens",
    ]
    assert ledger.summary().requests == 0


def test_https_cancellation_interrupts_a_dispatched_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, cancelled, interrupted = Event(), Event(), Event()

    class Socket:
        def settimeout(self, seconds: float) -> None:
            assert 0 < seconds <= 5.0

        def shutdown(self, how: int) -> None:
            interrupted.set()

    class Connection:
        def __init__(self, host: str, *, timeout: float) -> None:
            assert host == "api.openai.com" and timeout == 5.0
            self.sock = Socket()

        def connect(self) -> None:
            pass

        def request(
            self, method: str, path: str, *, body: bytes, headers: dict[str, str]
        ) -> None:
            assert method == "POST" and path == "/v1/responses"
            assert headers["Authorization"] == "Bearer " + _KEY
            started.set()
            interrupted.wait(timeout=5.0)
            raise OSError("interrupted")

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        "ai4algebra.candidates._http.http.client.HTTPSConnection", Connection
    )
    with ThreadPoolExecutor(max_workers=1) as worker:
        result = worker.submit(
            OpenAIHTTPS().post,
            "/responses",
            b"{}",
            key=SecretStr(_KEY),
            timeout_seconds=5.0,
            cancelled=cancelled,
        )
        assert started.wait(timeout=2.0)
        cancelled.set()
        with pytest.raises(TransportError, match="cancelled"):
            result.result(timeout=2.0)
        assert interrupted.is_set()


def test_provider_refuses_credential_serialization(tmp_path: Path) -> None:
    provider = OpenAIProposer(
        _config(tmp_path, "0.50"),
        BudgetLedger(tmp_path / "budget.db", "run", Decimal("0.50")),
    )
    with pytest.raises(TypeError, match="cannot be serialized"):
        pickle.dumps(provider)


@pytest.mark.parametrize("abort", ["timeout", "cancelled"])
def test_slow_connect_cannot_dispatch_after_caller_aborts(
    monkeypatch: pytest.MonkeyPatch, abort: str
) -> None:
    connecting, release, closed, dispatched, cancelled = (Event() for _ in range(5))

    class Connection:
        sock = None

        def __init__(self, host: str, *, timeout: float) -> None:
            assert host == "api.openai.com"

        def connect(self) -> None:
            connecting.set()
            assert release.wait(timeout=3.0)

        def request(
            self, method: str, path: str, *, body: bytes, headers: dict[str, str]
        ) -> None:
            dispatched.set()
            raise OSError("unexpected dispatch")

        def close(self) -> None:
            closed.set()

    monkeypatch.setattr(
        "ai4algebra.candidates._http.http.client.HTTPSConnection", Connection
    )
    with ThreadPoolExecutor(max_workers=1) as worker:
        result = worker.submit(
            OpenAIHTTPS().post,
            "/responses",
            b"{}",
            key=SecretStr(_KEY),
            timeout_seconds=0.1 if abort == "timeout" else 5.0,
            cancelled=cancelled,
        )
        try:
            assert connecting.wait(timeout=2.0)
            if abort == "cancelled":
                cancelled.set()
            with pytest.raises(TransportError, match=abort):
                result.result(timeout=2.0)
        finally:
            release.set()
        assert closed.wait(timeout=2.0)
        assert not dispatched.is_set()
