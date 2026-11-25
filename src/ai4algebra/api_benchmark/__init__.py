"""Benchmark external retrieval APIs independently of Lean proof search."""

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from statistics import median
from time import perf_counter, sleep
from typing import Literal

from ai4algebra.api_benchmark._http import (
    DirectHttpTransport,
    HttpTransport,
    RequestFailure,
    TransportFailure,
    media_type,
)
from ai4algebra.api_benchmark._queries import (
    SERVICES,
    Query,
    QuerySet,
    Service,
    load_queries,
)
from ai4algebra.api_benchmark._services import Status, parse_result, request_url
from ai4algebra.api_benchmark._settings import (
    BenchmarkConfigError,
    BenchmarkSettings,
    load_settings,
)

Skip = Literal["skipped_dry_run", "skipped_disabled"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class QueryResult:
    id: str
    service: Service
    category: str | None
    timestamp_utc: str
    status: Status | TransportFailure | Skip | Literal["http_error"]
    expected_name_count: int
    http_status: int | None = None
    latency_ms: float | None = None
    result_count: int | None = None
    ranked_names: tuple[str, ...] = ()
    service_result_count: int | None = None
    content_bytes: int | None = None
    content_sha256: str | None = None
    mime_type: str | None = None
    first_expected_rank: int | None = None
    reciprocal_rank: float | None = None


@dataclass(frozen=True)
class ServiceSummary:
    query_count: int
    attempted_count: int
    skipped_count: int
    success_count: int
    nonempty_count: int
    empty_count: int
    error_count: int
    success_rate: float | None
    nonempty_rate: float | None
    median_latency_ms: float | None
    labeled_query_count: int
    scored_query_count: int
    mrr_at_k: float | None
    hit_at_k: float | None


@dataclass(frozen=True)
class EndpointIdentity:
    base_url_sha256: str
    uses_default_base_url: bool


@dataclass(frozen=True)
class BenchmarkReport:
    schema_version: Literal[1]
    mode: Literal["dry_run", "live"]
    started_at_utc: str
    completed_at_utc: str
    query_file_sha256: str
    result_limit: int
    timeout_seconds: float
    max_response_bytes: int
    request_interval_seconds: float
    stacks_enabled: bool
    endpoints: dict[Service, EndpointIdentity]
    summaries: dict[Service, ServiceSummary]
    results: tuple[QueryResult, ...]

    @property
    def has_errors(self) -> bool:
        return any(summary.error_count for summary in self.summaries.values())

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, allow_nan=False) + "\n"


def _probe(
    query: Query,
    result: QueryResult,
    settings: BenchmarkSettings,
    transport: HttpTransport,
) -> QueryResult:
    url = request_url(query, settings)
    start = perf_counter()
    try:
        response = transport.get(
            url,
            timeout_seconds=settings.timeout_seconds,
            max_response_bytes=settings.max_response_bytes,
        )
    except RequestFailure as error:
        return replace(
            result,
            status=error.status,
            latency_ms=(perf_counter() - start) * 1000,
            http_status=error.http_status,
            mime_type=media_type(error.mime_type),
        )
    result = replace(
        result,
        latency_ms=(perf_counter() - start) * 1000,
        http_status=response.status,
        mime_type=media_type(response.mime_type),
    )
    if not 200 <= response.status < 300:
        return replace(result, status="http_error")
    if len(response.body) > settings.max_response_bytes:
        return replace(result, status="response_too_large")

    parsed = parse_result(query, response.body, result.mime_type, settings.result_limit)
    expected = set(query.expected_names)
    rank = next(
        (
            index
            for index, name in enumerate(parsed.ranked_names, start=1)
            if name in expected
        ),
        None,
    )
    reciprocal_rank: float | None = None
    if expected and query.service != "stacks" and parsed.status in {"ok", "empty"}:
        reciprocal_rank = 1 / rank if rank is not None else 0.0
    return replace(
        result,
        status=parsed.status,
        result_count=parsed.result_count,
        ranked_names=parsed.ranked_names,
        service_result_count=parsed.service_result_count,
        content_bytes=len(response.body),
        content_sha256=sha256(response.body).hexdigest(),
        first_expected_rank=rank,
        reciprocal_rank=reciprocal_rank,
    )


def _summarize(results: list[QueryResult]) -> ServiceSummary:
    latencies = [item.latency_ms for item in results if item.latency_ms is not None]
    successful = [item for item in results if item.status in {"ok", "empty"}]
    nonempty = sum(item.status == "ok" for item in successful)
    ranks = [
        item.reciprocal_rank for item in successful if item.reciprocal_rank is not None
    ]
    return ServiceSummary(
        query_count=len(results),
        attempted_count=len(latencies),
        skipped_count=len(results) - len(latencies),
        success_count=len(successful),
        nonempty_count=nonempty,
        empty_count=len(successful) - nonempty,
        error_count=len(latencies) - len(successful),
        success_rate=len(successful) / len(latencies) if latencies else None,
        nonempty_rate=nonempty / len(successful) if successful else None,
        median_latency_ms=median(latencies) if latencies else None,
        labeled_query_count=sum(item.expected_name_count > 0 for item in results),
        scored_query_count=len(ranks),
        mrr_at_k=sum(ranks) / len(ranks) if ranks else None,
        hit_at_k=sum(rank > 0 for rank in ranks) / len(ranks) if ranks else None,
    )


def run_benchmark(
    queries: QuerySet,
    settings: BenchmarkSettings,
    query_file_sha256: str,
    *,
    live: bool = False,
    service: Service | None = None,
    transport: HttpTransport | None = None,
) -> BenchmarkReport:
    """Run selected queries in file order and retain only response metadata and names."""
    selected = tuple(
        query
        for query in queries.queries
        if service is None or query.service == service
    )
    if not selected:
        raise BenchmarkConfigError(
            "benchmark query file has no queries for the selected service"
        )
    if transport is None:
        transport = DirectHttpTransport()

    included_services = tuple(
        name for name in SERVICES if any(query.service == name for query in selected)
    )
    defaults = BenchmarkSettings()
    start = _utc_now()
    next_request = 0.0
    results = []
    for query in selected:
        result = QueryResult(
            id=query.id,
            service=query.service,
            category=query.category,
            timestamp_utc=_utc_now(),
            status="skipped_dry_run",
            expected_name_count=len(query.expected_names),
        )
        if live:
            if query.service == "stacks" and not settings.stacks_enabled:
                result = replace(result, status="skipped_disabled")
            else:
                remaining = next_request - perf_counter()
                if remaining > 0:
                    sleep(remaining)
                next_request = perf_counter() + settings.request_interval_seconds
                result = _probe(
                    query,
                    replace(result, timestamp_utc=_utc_now()),
                    settings,
                    transport,
                )
        results.append(result)

    return BenchmarkReport(
        schema_version=1,
        mode="live" if live else "dry_run",
        started_at_utc=start,
        completed_at_utc=_utc_now(),
        query_file_sha256=query_file_sha256,
        result_limit=settings.result_limit,
        timeout_seconds=settings.timeout_seconds,
        max_response_bytes=settings.max_response_bytes,
        request_interval_seconds=settings.request_interval_seconds,
        stacks_enabled=settings.stacks_enabled,
        endpoints={
            name: EndpointIdentity(
                base_url_sha256=sha256(settings.base_url(name).encode()).hexdigest(),
                uses_default_base_url=settings.base_url(name)
                == defaults.base_url(name),
            )
            for name in included_services
        },
        summaries={
            name: _summarize([result for result in results if result.service == name])
            for name in included_services
        },
        results=tuple(results),
    )


__all__ = [
    "BenchmarkConfigError",
    "BenchmarkReport",
    "BenchmarkSettings",
    "load_queries",
    "load_settings",
    "run_benchmark",
]
