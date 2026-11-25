"""Budgeted Responses API adapter for structured tactic proposals."""

import json
import math
import sqlite3
import time
from collections.abc import Mapping
from threading import Event
from typing import Annotated, Literal, NoReturn, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from ai4algebra.config import DEFAULT_BASE_URL, Limits, RunConfig
from ai4algebra.contracts import (
    Argument,
    Candidate,
    Identifier,
    LeanName,
    Operation,
    _unique_fields,
)

from ._budget import ASTRA_STANDARD, BudgetError, BudgetLedger, Reservation, Usage
from ._http import (
    MAX_RESPONSE_BYTES,
    Endpoint,
    HttpResponse,
    OpenAIHTTPS,
    ResponsesTransport,
    TransportError,
)
from ._proposal import ProposalRequest, ProposalResult, ProviderStatus
from ._rules import GENERATOR_VERSION, MAX_OPERANDS

_MAX_BODY_BYTES = 65_536
_MAX_CANDIDATES = 32
_MAX_ATTEMPTS = 2
_INSTRUCTIONS = (
    "Propose Lean proof steps for the supplied goals using the typed JSON schema only. "
    "Use the supplied goal and local IDs and only the listed premise declarations. "
    "For exact, apply, and rewrite choose a lemma or local operand. Only exact and apply "
    "may have explicit arguments, with a lemma operand. Use forward direction and null "
    "location unless rewriting. Use a nonempty explicit list only for simp_only. "
    "Absent operands are null, absent arrays are empty. Return an empty list if none apply."
)


class _WireRecord(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)


class _WireArgument(_WireRecord):
    kind: Literal["local", "lemma"]
    reference: Annotated[str, Field(min_length=1, max_length=256)]


class _WireCandidate(_WireRecord):
    operation: Operation
    goal_id: Identifier
    lemma: LeanName | None
    local_id: Identifier | None
    arguments: Annotated[tuple[_WireArgument, ...], Field(max_length=MAX_OPERANDS)]
    direction: Literal["forward", "backward"]
    location: Identifier | None
    simp_lemmas: Annotated[tuple[LeanName, ...], Field(max_length=MAX_OPERANDS)]

    def to_candidate(self) -> Candidate:
        return Candidate(
            operation=self.operation,
            goal_id=self.goal_id,
            lemma=self.lemma,
            local_id=self.local_id,
            arguments=tuple(
                Argument(kind=arg.kind, reference=arg.reference)
                for arg in self.arguments
            ),
            direction=self.direction,
            location=self.location,
            simp_lemmas=self.simp_lemmas,
            provenance="openai",
            generator_version=GENERATOR_VERSION,
        )


class _WireOutput(_WireRecord):
    candidates: Annotated[tuple[_WireCandidate, ...], Field(max_length=_MAX_CANDIDATES)]


def _object_schema(properties: Mapping[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(properties),
        "additionalProperties": False,
    }


def _format(max_candidates: int) -> dict[str, object]:
    string = {"type": "string"}
    optional = {"type": ["string", "null"]}
    operand = _object_schema(
        {"kind": {"enum": ["local", "lemma"], "type": "string"}, "reference": string}
    )
    candidate = _object_schema(
        {
            "operation": {"enum": list(get_args(Operation)), "type": "string"},
            "goal_id": string,
            "lemma": optional,
            "local_id": optional,
            "arguments": {"type": "array", "items": operand, "maxItems": MAX_OPERANDS},
            "direction": {"enum": ["forward", "backward"], "type": "string"},
            "location": optional,
            "simp_lemmas": {"type": "array", "items": string, "maxItems": MAX_OPERANDS},
        }
    )
    return {
        "format": {
            "type": "json_schema",
            "name": "lean_tactic_candidates",
            "strict": True,
            "schema": _object_schema(
                {
                    "candidates": {
                        "type": "array",
                        "items": candidate,
                        "maxItems": max_candidates,
                    }
                }
            ),
        }
    }


def _json(data: object) -> bytes:
    return json.dumps(
        data, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _object(data: object) -> dict[str, object]:
    if not isinstance(data, dict) or any(not isinstance(key, str) for key in data):
        raise ValueError("expected JSON object")
    return cast(dict[str, object], data)


def _integer(data: object) -> int:
    if type(data) is not int or data < 0:
        raise ValueError("expected nonnegative integer")
    return data


def _load(response: HttpResponse) -> dict[str, object]:
    if len(response.body) > MAX_RESPONSE_BYTES:
        raise ValueError("response exceeds body limit")
    return _object(json.loads(response.body, object_pairs_hook=_unique_fields))


def _usage(response: Mapping[str, object]) -> Usage:
    raw = _object(response.get("usage"))
    input_tokens = _integer(raw.get("input_tokens"))
    output_tokens = _integer(raw.get("output_tokens"))
    if _integer(raw.get("total_tokens")) != input_tokens + output_tokens:
        raise ValueError("inconsistent response usage totals")
    input_details = _object(raw.get("input_tokens_details") or {})
    output_details = _object(raw.get("output_tokens_details") or {})
    if _integer(output_details.get("reasoning_tokens", 0)) > output_tokens:
        raise ValueError("invalid reasoning token count")
    writes = _integer(input_details.get("cache_write_tokens", 0))
    lifetimes = _object(input_details.get("cache_write_tokens_details") or {})
    writes = max(writes, sum(_integer(count) for count in lifetimes.values()))
    return Usage(
        input_tokens,
        output_tokens,
        _integer(input_details.get("cached_tokens", 0)),
        writes,
    )


def _decode(response: Mapping[str, object], max_candidates: int) -> ProposalResult:
    if response.get("status") != "completed":
        return ProposalResult("incomplete")
    output = response.get("output")
    if not isinstance(output, list):
        return ProposalResult("malformed")
    texts: list[str] = []
    try:
        for value in output:
            item = _object(value)
            if item.get("type") == "reasoning":
                continue
            content = item.get("content")
            if item.get("type") != "message" or not isinstance(content, list):
                return ProposalResult("malformed")
            for part in content:
                block = _object(part)
                if block.get("type") == "refusal":
                    return ProposalResult("refused")
                text = block.get("text")
                if block.get("type") != "output_text" or not isinstance(text, str):
                    return ProposalResult("malformed")
                texts.append(text)
        if len(texts) != 1:
            return ProposalResult("malformed")
        # Reject duplicate JSON fields before strict schema validation.
        json.loads(texts[0], object_pairs_hook=_unique_fields)
        decoded = _WireOutput.model_validate_json(texts[0])
        if len(decoded.candidates) > max_candidates:
            return ProposalResult("malformed")
        return ProposalResult(
            "ok", tuple(candidate.to_candidate() for candidate in decoded.candidates)
        )
    except (ValueError, RecursionError):
        return ProposalResult("malformed")


class OpenAIProposer:
    """Text-only Astra generation with exact preflight and shared reservations."""

    def __getstate__(self) -> NoReturn:
        raise TypeError("a credential-bearing provider cannot be serialized")

    def __init__(
        self,
        config: RunConfig,
        ledger: BudgetLedger,
        transport: ResponsesTransport | None = None,
    ) -> None:
        self._config = RunConfig.from_json(config.to_json())
        self._key = config.openai_api_key
        self._ledger = ledger
        self._transport = OpenAIHTTPS() if transport is None else transport
        if self._ledger.budget_usd > self._config.api_budget_usd:
            raise BudgetError("ledger budget exceeds configuration")

    def propose(
        self,
        request: ProposalRequest,
        limits: Limits,
        *,
        timeout_seconds: float | None = None,
        cancelled: Event | None = None,
    ) -> ProposalResult:
        key = self._key
        if (
            self._config.provider != "openai"
            or not self._config.allow_paid_api
            or not isinstance(key, SecretStr)
            or not key.get_secret_value().strip()
            or self._ledger.budget_usd == 0
        ):
            return ProposalResult("disabled")
        if (
            self._config.model,
            self._config.base_url,
            self._config.reasoning_effort,
        ) != (ASTRA_STANDARD.model, DEFAULT_BASE_URL, "high"):
            return ProposalResult("pricing_mismatch")
        timeout = min(
            limits.step_timeout_seconds, self._config.limits.step_timeout_seconds
        )
        if timeout_seconds is not None:
            if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
                raise ValueError("provider timeout must be finite and nonnegative")
            timeout = min(timeout, timeout_seconds)
        deadline = time.monotonic() + timeout
        if cancelled is not None and cancelled.is_set():
            return ProposalResult("cancelled")
        if timeout <= 0:
            return ProposalResult("timeout")
        max_candidates = min(
            limits.max_candidates, self._config.limits.max_candidates, _MAX_CANDIDATES
        )
        output_bound = min(
            limits.max_output_tokens,
            self._config.limits.max_output_tokens,
            ASTRA_STANDARD.max_output_tokens,
        )
        if output_bound < 16:
            return ProposalResult("input_limit")
        # These are all context-bearing fields. Generation adds only processing controls.
        context = {
            "model": self._config.model,
            "input": _json(request.prompt_data()).decode("utf-8"),
            "instructions": _INSTRUCTIONS,
            "reasoning": {"effort": self._config.reasoning_effort},
            "text": _format(max_candidates),
            "tools": [],
            "tool_choice": "none",
            "truncation": "disabled",
        }
        count_payload = _json(context)
        if len(count_payload) > _MAX_BODY_BYTES:
            return ProposalResult("input_limit")
        try:
            if self._ledger.summary().blocked:
                return ProposalResult("pricing_mismatch")
        except sqlite3.Error:
            return ProposalResult("unavailable")
        try:
            count = self._post(
                "/responses/input_tokens", count_payload, key, deadline, cancelled
            )
            if count.status_code != 200:
                return ProposalResult("unavailable", token_count_requests=1)
            preflight = _load(count)
            if preflight.get("object") != "response.input_tokens":
                return ProposalResult("malformed", token_count_requests=1)
            input_tokens = _integer(preflight.get("input_tokens"))
        except TransportError as exc:
            return ProposalResult(exc.status, token_count_requests=1)
        except (ValueError, RecursionError):
            return ProposalResult("malformed", token_count_requests=1)
        if (
            not 0
            < input_tokens
            <= min(
                limits.max_input_tokens,
                self._config.limits.max_input_tokens,
                ASTRA_STANDARD.max_input_tokens,
            )
        ):
            return ProposalResult("input_limit", token_count_requests=1)
        generation = _json(
            {
                **context,
                "max_output_tokens": output_bound,
                "service_tier": ASTRA_STANDARD.tier,
                "prompt_cache_options": {"mode": "explicit", "prewarm": False},
                "background": False,
                "stream": False,
                "store": False,
            }
        )
        return self._run(
            generation,
            key,
            input_tokens,
            output_bound,
            max_candidates,
            deadline,
            cancelled,
        )

    def _run(
        self,
        payload: bytes,
        key: SecretStr,
        input_tokens: int,
        output_bound: int,
        max_candidates: int,
        deadline: float,
        cancelled: Event | None,
    ) -> ProposalResult:
        attempts = 0
        status: ProviderStatus = "unavailable"
        while attempts < _MAX_ATTEMPTS:
            if cancelled is not None and cancelled.is_set():
                return ProposalResult(
                    "cancelled", requests=attempts, token_count_requests=1
                )
            if time.monotonic() >= deadline:
                return ProposalResult(
                    "timeout", requests=attempts, token_count_requests=1
                )
            try:
                reservation = self._ledger.reserve(input_tokens, output_bound)
                if reservation is None:
                    return ProposalResult(
                        "budget_exhausted", requests=attempts, token_count_requests=1
                    )
                attempts += 1
                response = self._post("/responses", payload, key, deadline, cancelled)
                if response.status_code == 429 or 500 <= response.status_code < 600:
                    status = "unavailable"
                    continue
                if response.status_code != 200:
                    break
                result = self._handle_response(response, reservation, max_candidates)
                return ProposalResult(result.status, result.candidates, attempts, 1)
            except TransportError as exc:
                status = exc.status
                if status not in ("timeout", "unavailable"):
                    break
            except (BudgetError, sqlite3.Error):
                break
        return ProposalResult(status, requests=attempts, token_count_requests=1)

    def _handle_response(
        self, response: HttpResponse, reservation: Reservation, max_candidates: int
    ) -> ProposalResult:
        try:
            data = _load(response)
        except (ValueError, RecursionError):
            return ProposalResult("malformed")
        if (data.get("model"), data.get("service_tier")) != (
            ASTRA_STANDARD.model,
            ASTRA_STANDARD.tier,
        ):
            self._ledger.block()
            return ProposalResult("pricing_mismatch")
        output = data.get("output")
        if (
            data.get("tools")
            or data.get("conversation")
            or data.get("background")
            or (
                isinstance(output, list)
                and any(
                    isinstance(item, dict)
                    and item.get("type") not in ("message", "reasoning")
                    for item in output
                )
            )
        ):
            self._ledger.block()
            return ProposalResult("pricing_mismatch")
        try:
            usage = _usage(data)
        except ValueError:
            return ProposalResult("malformed")
        try:
            self._ledger.settle(reservation, usage)
        except BudgetError:
            return ProposalResult("pricing_mismatch")
        return _decode(data, max_candidates)

    def _post(
        self,
        endpoint: Endpoint,
        payload: bytes,
        key: SecretStr,
        deadline: float,
        cancelled: Event | None,
    ) -> HttpResponse:
        if cancelled is not None and cancelled.is_set():
            raise TransportError("cancelled")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TransportError("timeout")
        try:
            return self._transport.post(
                endpoint,
                payload,
                key=key,
                timeout_seconds=remaining,
                cancelled=cancelled,
            )
        except TimeoutError:
            raise TransportError("timeout") from None
        except OSError:
            raise TransportError("unavailable") from None
