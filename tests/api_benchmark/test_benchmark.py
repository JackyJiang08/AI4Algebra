import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from ai4algebra import api_benchmark
from ai4algebra.api_benchmark import (
    BenchmarkConfigError,
    BenchmarkSettings,
    load_queries,
    load_settings,
    run_benchmark,
)
from ai4algebra.api_benchmark import __main__ as benchmark_cli
from ai4algebra.api_benchmark.__main__ import main
from ai4algebra.api_benchmark._http import HttpResponse, RequestFailure
from ai4algebra.api_benchmark._queries import Query, QuerySet


class FakeTransport:
    def __init__(self, *responses: HttpResponse | RequestFailure) -> None:
        self.responses: Iterator[HttpResponse | RequestFailure] = iter(responses)
        self.calls: list[tuple[str, float, int]] = []

    def get(
        self, url: str, *, timeout_seconds: float, max_response_bytes: int
    ) -> HttpResponse:
        self.calls.append((url, timeout_seconds, max_response_bytes))
        response = next(self.responses)
        if isinstance(response, RequestFailure):
            raise response
        return response


def test_dry_run_and_disabled_stacks_do_not_send_requests() -> None:
    plan = QuerySet(queries=(Query(id="tag", service="stacks", query="00GJ"),))
    transport = FakeTransport()

    dry = run_benchmark(plan, BenchmarkSettings(), "a" * 64, transport=transport)
    skipped = run_benchmark(
        plan, BenchmarkSettings(), "a" * 64, live=True, transport=transport
    )

    assert transport.calls == []
    assert dry.results[0].status == "skipped_dry_run"
    assert skipped.results[0].status == "skipped_disabled"
    for report in (dry, skipped):
        assert not report.has_errors
        summary = report.summaries["stacks"]
        assert summary.skipped_count == 1
        assert summary.success_rate is None
        assert summary.median_latency_ms is None
        assert summary.hit_at_k is None
    assert (
        run_benchmark(
            plan,
            replace(BenchmarkSettings(), stacks_enabled=True),
            "a" * 64,
            transport=transport,
        )
        .results[0]
        .status
        == "skipped_dry_run"
    )


def test_endpoints_encoded_identifiers_and_response_metadata() -> None:
    search = '"mul_one" & ?x + α'
    plan = QuerySet(
        queries=(
            Query(id="tag", service="stacks", query="00GJ"),
            Query(id="semantic", service="leanexplore", query=search),
            Query(
                id="name", service="loogle", query=search, expected_names=("mul_one",)
            ),
        )
    )
    settings = replace(
        BenchmarkSettings(),
        stacks_enabled=True,
        request_interval_seconds=0,
        result_limit=2,
    )
    statement = b"<p>Material statement text that never appears in the report.</p>"
    transport = FakeTransport(
        HttpResponse(200, "Text/HTML; charset=UTF-8", statement),
        HttpResponse(200, "application/json", b'{"results":[{"name":"one_mul"}]}'),
        HttpResponse(
            200,
            "application/json",
            b'{"count":12,"hits":[{"name":"one_mul","type":"proof secret"},'
            b'{"name":"mul_one"},{"name":"cut_off"}]}',
        ),
    )
    report = run_benchmark(plan, settings, "a" * 64, live=True, transport=transport)

    assert transport.calls[0] == (
        "https://stacks.math.columbia.edu/data/tag/00GJ/content/statement",
        20,
        1_048_576,
    )
    leanexplore = urlsplit(transport.calls[1][0])
    loogle = urlsplit(transport.calls[2][0])
    assert (leanexplore.netloc, leanexplore.path) == (
        "www.leanexplore.com",
        "/api/v2/search",
    )
    assert parse_qs(leanexplore.query) == {
        "q": [search],
        "limit": ["2"],
        "packages": ["Mathlib"],
    }
    assert (loogle.netloc, loogle.path) == ("loogle.lean-lang.org", "/json")
    assert parse_qs(loogle.query) == {"q": [search]}
    stacks, lean, names = report.results
    assert stacks.content_sha256 == sha256(statement).hexdigest()
    assert stacks.content_bytes == len(statement)
    assert stacks.mime_type == "text/html"
    assert stacks.result_count == 1
    assert stacks.ranked_names == ()
    assert lean.reciprocal_rank is None
    assert names.ranked_names == ("one_mul", "mul_one")
    assert names.result_count == 3 and names.service_result_count == 12
    assert names.first_expected_rank == 2 and names.reciprocal_rank == 0.5
    assert datetime.fromisoformat(names.timestamp_utc).utcoffset() == timedelta(0)
    assert report.summaries["loogle"].mrr_at_k == 0.5
    assert report.summaries["loogle"].hit_at_k == 1.0
    assert not any(
        word in report.to_json() for word in ("Material statement", "proof secret")
    )


@pytest.mark.parametrize(
    ("response", "status"),
    [
        (HttpResponse(200, "application/json", b"{}"), "malformed_response"),
        (HttpResponse(200, "application/json", b"{"), "malformed_response"),
        (HttpResponse(200, "text/html", b"<p>Oops</p>"), "malformed_response"),
        (
            HttpResponse(200, "application/json", b'{"error":"secret-sentinel"}'),
            "api_error",
        ),
        (
            HttpResponse(200, "application/json", b'{"hits": [], "count": true}'),
            "malformed_response",
        ),
        (
            HttpResponse(200, "application/json", b'{"hits":[{}],"count":1}'),
            "malformed_response",
        ),
        (HttpResponse(429, "text/html", b"secret-sentinel"), "http_error"),
        (HttpResponse(302, "text/html", b"secret-sentinel"), "http_error"),
        (HttpResponse(200, "text/html", b"X" * 65), "response_too_large"),
        (RequestFailure("timeout", 200, "application/json"), "timeout"),
        (RequestFailure("network_error"), "network_error"),
    ],
)
def test_distinct_live_failures(
    response: HttpResponse | RequestFailure, status: str
) -> None:
    queries = QuerySet(
        queries=(
            Query(id="example", service="loogle", query="q", expected_names=("gold",)),
        )
    )
    report = run_benchmark(
        queries,
        replace(BenchmarkSettings(), max_response_bytes=64),
        "a" * 64,
        live=True,
        transport=FakeTransport(response),
    )
    result = report.results[0]
    assert result.status == status
    assert result.latency_ms is not None and result.latency_ms >= 0
    assert result.first_expected_rank is None and result.reciprocal_rank is None
    assert result.ranked_names == ()
    assert "secret-sentinel" not in report.to_json()
    assert report.has_errors
    summary = report.summaries["loogle"]
    assert summary.error_count == 1
    assert summary.success_rate == 0
    assert summary.nonempty_rate is None
    assert summary.mrr_at_k is None and summary.hit_at_k is None


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<p> </p>",
        b"<p>Not found.</p>",
        b"<html><body><p>Login</p></body></html>",
        b"<div><script>redirect()</script></div>",
        b"<p>\xff</p>",
    ],
)
def test_stacks_rejects_empty_or_nonstatement_html(body: bytes) -> None:
    plan = QuerySet(queries=(Query(id="tag", service="stacks", query="00GJ"),))
    report = run_benchmark(
        plan,
        replace(BenchmarkSettings(), stacks_enabled=True),
        "a" * 64,
        live=True,
        transport=FakeTransport(HttpResponse(200, "text/html", body)),
    )
    assert report.results[0].status == "malformed_response"
    assert report.results[0].content_sha256 == sha256(body).hexdigest()


def test_relevance_only_uses_labeled_successful_responses() -> None:
    queries = QuerySet(
        queries=tuple(
            Query(
                id=case,
                service="leanexplore",
                query="test",
                expected_names=("gold",) if case != "unlabeled" else (),
            )
            for case in ("hit", "empty", "error", "unlabeled")
        )
    )
    empty = HttpResponse(200, "application/json", b'{"results":[]}')
    hit = HttpResponse(200, "application/json", b'{"results":[{"name":"gold"}]}')
    report = run_benchmark(
        queries,
        replace(BenchmarkSettings(), request_interval_seconds=0),
        "a" * 64,
        live=True,
        service="leanexplore",
        transport=FakeTransport(hit, empty, RequestFailure("timeout"), hit),
    )
    assert report.results[1].status == "empty"
    assert report.results[1].result_count == 0
    assert report.results[1].reciprocal_rank == 0.0
    assert report.results[1].ranked_names == ()
    summary = report.summaries["leanexplore"]
    assert summary.labeled_query_count == 3 and summary.scored_query_count == 2
    assert summary.mrr_at_k == 0.5 and summary.hit_at_k == 0.5
    assert summary.success_rate == 0.75 and summary.nonempty_rate == pytest.approx(
        2 / 3
    )
    assert summary.median_latency_ms is not None


def test_requests_are_rate_spaced(monkeypatch: pytest.MonkeyPatch) -> None:
    current_time = 10.0
    starts: list[float] = []

    def now() -> float:
        return current_time

    def fake_sleep(seconds: float) -> None:
        nonlocal current_time
        current_time += seconds

    class TimedTransport:
        def get(
            self, url: str, *, timeout_seconds: float, max_response_bytes: int
        ) -> HttpResponse:
            starts.append(current_time)
            fake_sleep(0.25)
            return HttpResponse(200, "application/json", b'{"hits":[],"count":0}')

    monkeypatch.setattr(api_benchmark, "perf_counter", now)
    monkeypatch.setattr(api_benchmark, "sleep", fake_sleep)
    plan = QuerySet(
        queries=tuple(Query(id=str(i), service="loogle", query="Q") for i in range(3))
    )
    report = run_benchmark(
        plan, BenchmarkSettings(), "a" * 64, live=True, transport=TimedTransport()
    )

    assert starts == [10.0, 11.0, 12.0]
    assert [result.latency_ms for result in report.results] == [250] * 3


def test_settings_precedence_and_no_secret_serialization(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "OPENAI_API_KEY=private-dotenv-secret\n"
        "AI4ALGEBRA_LOOGLE_BASE_URL=http://127.0.0.1:9876/private-path-sentinel/\n"
        "AI4ALGEBRA_API_RESULT_LIMIT=3\n",
        encoding="utf-8",
    )
    env = {"OPENAI_API_KEY": "private-env-secret", "AI4ALGEBRA_API_RESULT_LIMIT": "2"}
    settings = load_settings(dotenv, environ=env)
    assert settings.result_limit == 2
    assert settings.loogle_base_url == "http://127.0.0.1:9876/private-path-sentinel"
    queries = QuerySet(queries=(Query(id="name", service="loogle", query="hello"),))
    report = run_benchmark(queries, settings, "a" * 64, transport=FakeTransport())
    assert not report.endpoints["loogle"].uses_default_base_url
    assert (
        report.endpoints["loogle"].base_url_sha256
        == sha256(settings.loogle_base_url.encode()).hexdigest()
    )
    assert all(
        text not in report.to_json()
        for text in (
            "private-dotenv-secret",
            "private-env-secret",
            "private-path-sentinel",
        )
    )
    assert "private-env-secret" not in repr(settings)
    assert "private-dotenv-secret" not in repr(settings)

    dotenv.write_text(
        "OPENAI_API_KEY=private-dotenv-secret\n"
        "AI4ALGEBRA_LOOGLE_BASE_URL=https://example.test/${OPENAI_API_KEY}/\n",
        encoding="utf-8",
    )
    assert load_settings(dotenv, environ={}).loogle_base_url.endswith(
        "${OPENAI_API_KEY}"
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("LOOGLE_BASE_URL", "http://example.test"),
        ("LOOGLE_BASE_URL", "https://private-sentinel@example.test"),
        ("LOOGLE_BASE_URL", "https://example.test/?private-sentinel"),
        ("LOOGLE_BASE_URL", "https://example.test/#private-sentinel"),
        ("LOOGLE_BASE_URL", "https://example.test:private-sentinel"),
        ("API_TIMEOUT_SECONDS", "inf"),
        ("API_MAX_RESPONSE_BYTES", "0"),
        ("API_RESULT_LIMIT", "101"),
        ("API_REQUEST_INTERVAL_SECONDS", "nan"),
        ("STACKS_API_ENABLED", "private-sentinel"),
    ],
)
def test_invalid_settings_never_echo_values(
    tmp_path: Path, key: str, value: str
) -> None:
    with pytest.raises(BenchmarkConfigError, match=f"AI4ALGEBRA_{key}") as error:
        load_settings(tmp_path / ".env", environ={f"AI4ALGEBRA_{key}": value})
    assert "private-sentinel" not in str(error.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"queries": [{"id": "a", "service": "loogle", "query": "Q"}]},
        {
            "schema_version": True,
            "queries": [{"id": "a", "service": "loogle", "query": "Q"}],
        },
        {
            "schema_version": 1,
            "queries": [{"id": "a", "service": "stacks", "query": "00gj"}],
        },
        {
            "schema_version": 1,
            "queries": [
                {
                    "id": "a",
                    "service": "stacks",
                    "query": "00GJ",
                    "expected_names": ["00GJ"],
                }
            ],
        },
        {
            "schema_version": 1,
            "queries": [{"id": "a", "service": "loogle", "query": "X" * 1001}],
        },
        {
            "schema_version": 1,
            "queries": [
                {"id": "a", "service": "loogle", "query": "Q"},
                {"id": "a", "service": "leanexplore", "query": "R"},
            ],
        },
        {
            "schema_version": 1,
            "queries": [
                {"id": f"id-{i}", "service": "loogle", "query": "Q"} for i in range(101)
            ],
        },
    ],
)
def test_invalid_query_files_are_rejected(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "queries.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BenchmarkConfigError, match="version 1 benchmark query file"):
        load_queries(path)


def test_cli_file_filter_and_live_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "queries.json"
    source.write_text(
        '{"schema_version":1,"queries":[{"id":"a","service":"loogle","query":"Q"},'
        '{"id":"b","service":"stacks","query":"00GJ"}]}',
        encoding="utf-8",
    )
    destination = tmp_path / "run" / "report.json"
    transport = FakeTransport(HttpResponse(503, "text/html", b"private-sentinel"))
    monkeypatch.setattr(api_benchmark, "DirectHttpTransport", lambda: transport)
    monkeypatch.setattr(
        benchmark_cli, "load_settings", lambda path: load_settings(path, environ={})
    )
    args = [
        "--queries",
        str(source),
        "--output",
        str(destination),
        "--dotenv",
        str(tmp_path / ".env"),
    ]

    assert main(args + ["--service", "loogle"]) == 0
    assert transport.calls == []
    report = json.loads(destination.read_text(encoding="utf-8"))
    assert [result["id"] for result in report["results"]] == ["a"]
    assert report["results"][0]["status"] == "skipped_dry_run"
    assert main(args + ["--live", "--service", "stacks"]) == 0
    assert transport.calls == []
    assert main(args + ["--live"]) == 1
    report = json.loads(destination.read_text(encoding="utf-8"))
    assert [result["status"] for result in report["results"]] == [
        "http_error",
        "skipped_disabled",
    ]
    captured = capsys.readouterr()
    assert "Wrote benchmark report" in captured.out
    assert "private-sentinel" not in captured.out + captured.err
