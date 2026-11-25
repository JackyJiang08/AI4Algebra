"""Endpoint and response formats for each retrieval service."""

import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import urlencode

from ai4algebra.api_benchmark._queries import Query, valid_name
from ai4algebra.api_benchmark._settings import BenchmarkSettings
from ai4algebra.contracts import _unique_fields

Status = Literal["ok", "empty", "api_error", "malformed_response"]


@dataclass(frozen=True)
class ParsedResult:
    status: Status
    result_count: int | None = None
    ranked_names: tuple[str, ...] = ()
    service_result_count: int | None = None


def request_url(query: Query, settings: BenchmarkSettings) -> str:
    base_url = settings.base_url(query.service)
    if query.service == "stacks":
        return f"{base_url}/data/tag/{query.query}/content/statement"
    if query.service == "leanexplore":
        params = urlencode(
            {"q": query.query, "limit": settings.result_limit, "packages": "Mathlib"}
        )
        return f"{base_url}/search?{params}"
    return f"{base_url}/json?{urlencode({'q': query.query})}"


class _StatementFragment(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.valid_markup = False
        self.is_page = False
        self.text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"html", "head", "body", "title", "form", "script", "style"}:
            self.is_page = True
        if tag in {"p", "div", "span", "section", "article", "blockquote", "ol", "ul"}:
            self.valid_markup = True

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data.strip())


def _statement_result(body: bytes, mime_type: str | None) -> ParsedResult:
    if mime_type not in {"text/html", "application/xhtml+xml"}:
        return ParsedResult("malformed_response")
    fragment = _StatementFragment()
    try:
        fragment.feed(body.decode("utf-8"))
        fragment.close()
    except (ValueError, AssertionError):
        return ParsedResult("malformed_response")
    text = " ".join(fragment.text).casefold().rstrip(".")
    if (
        not fragment.valid_markup
        or fragment.is_page
        or not any(char.isalnum() for char in text)
        or text
        in {"not found", "404 not found", "access denied", "forbidden", "unauthorized"}
    ):
        return ParsedResult("malformed_response")
    return ParsedResult("ok", result_count=1)


def parse_result(
    query: Query, body: bytes, mime_type: str | None, result_limit: int
) -> ParsedResult:
    if query.service == "stacks":
        return _statement_result(body, mime_type)
    if mime_type != "application/json" and not (
        mime_type is not None and mime_type.endswith("+json")
    ):
        return ParsedResult("malformed_response")
    try:
        payload: object = json.loads(body, object_pairs_hook=_unique_fields)
    except (ValueError, RecursionError):
        return ParsedResult("malformed_response")
    if not isinstance(payload, dict):
        return ParsedResult("malformed_response")
    if "error" in payload:
        return ParsedResult("api_error")

    entries: object = payload.get("hits" if query.service == "loogle" else "results")
    if not isinstance(entries, list):
        return ParsedResult("malformed_response")
    service_count: int | None = None
    if query.service == "loogle":
        count: object = payload.get("count")
        if type(count) is not int or count < len(entries):
            return ParsedResult("malformed_response")
        service_count = count

    names: list[str] = []
    for entry in entries:
        name: object = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not valid_name(name):
            return ParsedResult("malformed_response")
        if len(names) < result_limit:
            names.append(name)
    return ParsedResult(
        "ok" if entries else "empty",
        result_count=len(entries),
        ranked_names=tuple(names),
        service_result_count=service_count,
    )
