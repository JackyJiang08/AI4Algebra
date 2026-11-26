"""Load run limits and provider settings without persisting credentials."""

import json
import os
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated, Final, Literal

from dotenv import dotenv_values
from pydantic import (
    ConfigDict,
    Field,
    PrivateAttr,
    SecretStr,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from ai4algebra.contracts import Record, _unique_fields

DEFAULT_BASE_URL: Final = "https://api.openai.com/v1"
MAX_API_BUDGET_USD: Final = Decimal("0.50")

_PROVIDER_KEYS = {
    "provider": "AI4ALGEBRA_LLM_PROVIDER",
    "model": "AI4ALGEBRA_LLM_MODEL",
    "base_url": "AI4ALGEBRA_LLM_BASE_URL",
    "reasoning_effort": "AI4ALGEBRA_LLM_REASONING_EFFORT",
    "allow_paid_api": "AI4ALGEBRA_ALLOW_PAID_API",
    "api_budget_usd": "AI4ALGEBRA_API_BUDGET_USD",
}


class ConfigError(ValueError):
    """An invalid or unavailable application configuration."""


class Limits(Record):
    max_depth: Annotated[int, Field(gt=0)] = 8
    max_nodes: Annotated[int, Field(gt=0)] = 32
    max_candidates: Annotated[int, Field(gt=0)] = 16
    max_steps: Annotated[int, Field(gt=0)] = 128
    step_timeout_seconds: Annotated[float, Field(gt=0)] = 60.0
    task_timeout_seconds: Annotated[float, Field(gt=0)] = 120.0
    max_input_tokens: Annotated[int, Field(gt=0)] = 4096
    max_output_tokens: Annotated[int, Field(gt=0)] = 1024


class RunConfig(Record):
    """Effective settings suitable for public run artifacts."""

    model_config = ConfigDict(hide_input_in_errors=True)
    limits: Limits = Field(default_factory=Limits)
    provider: Literal["deterministic", "openai"] = "deterministic"
    model: Literal["gpt-6.2-astra"] = "gpt-6.2-astra"
    base_url: Literal["https://api.openai.com/v1"] = DEFAULT_BASE_URL
    reasoning_effort: Literal["high"] = "high"
    allow_paid_api: bool = False
    api_budget_usd: Annotated[Decimal, Field(ge=0, le=MAX_API_BUDGET_USD)] = (
        MAX_API_BUDGET_USD
    )
    _openai_api_key: SecretStr | None = PrivateAttr(default=None)

    @field_validator("api_budget_usd", mode="before")
    @classmethod
    def _parse_wire_budget(cls, value: object, info: ValidationInfo) -> object:
        if info.mode == "json":
            if not isinstance(value, str):
                raise ValueError("wire budget must be a decimal string")
            return _decimal(value, "api_budget_usd")
        return value

    def __getstate__(self) -> dict[str, object]:
        state = super().__getstate__()
        state["__pydantic_private__"] = {"_openai_api_key": None}
        return state

    @property
    def openai_api_key(self) -> SecretStr | None:
        return self._openai_api_key

    @property
    def paid_enabled(self) -> bool:
        """Whether this configuration has a credential and enables paid calls."""
        return self._live_requested and self.openai_api_key is not None

    @property
    def _live_requested(self) -> bool:
        return (
            self.provider == "openai"
            and self.allow_paid_api
            and self.api_budget_usd > 0
        )


def _read_config(path: str | Path | None) -> dict[str, object]:
    if path is None:
        return {}
    try:
        data = json.loads(
            Path(path).read_text(encoding="utf-8-sig"),
            parse_float=Decimal,
            object_pairs_hook=_unique_fields,
        )
    except (OSError, ValueError):
        raise ConfigError("could not read the JSON configuration file") from None
    if not isinstance(data, dict):
        raise ConfigError("configuration file must contain a JSON object")
    return dict(data)


def _decimal(value: object, label: str) -> Decimal:
    if not isinstance(value, (str, int, Decimal)) or isinstance(value, bool):
        raise ConfigError(f"{label} must be a finite decimal amount")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ConfigError(f"{label} must be a finite decimal amount") from None
    if not amount.is_finite() or not Decimal("0") <= amount <= MAX_API_BUDGET_USD:
        raise ConfigError(f"{label} must be between USD 0 and USD {MAX_API_BUDGET_USD}")
    return amount


def _bool(value: str, label: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ConfigError(f"{label} must be true or false")
    return normalized == "true"


def _environment_settings(dotenv_path: str | Path | None) -> Mapping[str, str | None]:
    try:
        return dotenv_values(
            dotenv_path=Path(".env") if dotenv_path is None else dotenv_path,
            encoding="utf-8-sig",
            interpolate=False,
        )
    except (OSError, ValueError):
        raise ConfigError("could not read dotenv settings") from None


def _override_limits(
    config: dict[str, object], environment: Mapping[str, str | None]
) -> None:
    limits = config.get("limits", {})
    if not isinstance(limits, dict):
        raise ConfigError("limits must be a JSON object")
    limits = dict(limits)
    for name in Limits.model_fields.keys() - {"schema_version"}:
        key = f"AI4ALGEBRA_{name.upper()}"
        value = environment.get(key)
        if value is None:
            continue
        try:
            limits[name] = float(value) if name.endswith("_seconds") else int(value)
        except ValueError:
            raise ConfigError(f"{key} must be a positive number") from None
    config["limits"] = limits


def load_config(
    path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    dotenv_path: str | Path | None = None,
) -> RunConfig:
    """Read JSON settings, applying dotenv and environment overrides in that order."""
    config = _read_config(path)
    environment = dict(_environment_settings(dotenv_path))
    environment.update(os.environ if environ is None else environ)
    for field, key in _PROVIDER_KEYS.items():
        value = environment.get(key)
        if value is None:
            continue
        config[field] = _bool(value, key) if field == "allow_paid_api" else value
    if "api_budget_usd" in config:
        config["api_budget_usd"] = _decimal(config["api_budget_usd"], "api_budget_usd")
    _override_limits(config, environment)
    try:
        result = RunConfig.model_validate(config)
    except ValidationError as exc:
        fields = {
            str(issue["loc"][0])
            for issue in exc.errors(
                include_input=False, include_context=False, include_url=False
            )
            if issue["loc"]
        }
        known = fields & RunConfig.model_fields.keys()
        label = ", ".join(sorted(known)) if known else "unknown fields or version"
        raise ConfigError(f"invalid run configuration ({label})") from None
    if result._live_requested:
        key = (environment.get("OPENAI_API_KEY") or "").strip()
        if not key:
            raise ConfigError("OPENAI_API_KEY is required for live OpenAI proposals")
        result._openai_api_key = SecretStr(key)
    return result
