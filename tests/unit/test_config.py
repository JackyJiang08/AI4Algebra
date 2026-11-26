import json
import pickle
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai4algebra.config import ConfigError, Limits, RunConfig, load_config

LIVE_SETTINGS = {
    "AI4ALGEBRA_LLM_PROVIDER": "openai",
    "AI4ALGEBRA_ALLOW_PAID_API": "true",
}
_OVER_BUDGET = "0.5000000000000000000000000000000000001"


def test_defaults_support_offline_runs(tmp_path: Path) -> None:
    config = load_config(environ={}, dotenv_path=tmp_path / ".env")
    assert config == RunConfig()
    assert config.provider == "deterministic"
    assert config.model == "gpt-6.2-astra"
    assert config.reasoning_effort == "high"
    assert config.api_budget_usd == Decimal("0.50")
    assert config.limits == Limits()
    assert not config.paid_enabled
    assert config.openai_api_key is None
    assert RunConfig.from_json(config.to_json()) == config


def test_file_dotenv_environment_precedence_and_sanitized_round_trip(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "run.json"
    settings.write_text(
        '{"api_budget_usd":0.25,"limits":{"max_depth":6,"max_steps":25}}',
        encoding="utf-8",
    )
    dotenv = tmp_path / ".env"
    sentinel = "credential-sentinel"
    dotenv.write_text(
        f'OPENAI_API_KEY="{sentinel}"\n'
        "AI4ALGEBRA_LLM_PROVIDER=openai\n"
        "AI4ALGEBRA_ALLOW_PAID_API=true\n"
        "AI4ALGEBRA_API_BUDGET_USD=0.35\n"
        "AI4ALGEBRA_MAX_DEPTH=5\n",
        encoding="utf-8",
    )
    config = load_config(
        settings, {"AI4ALGEBRA_API_BUDGET_USD": "0.50"}, dotenv_path=dotenv
    )
    assert config.limits.max_depth == 5
    assert config.limits.max_steps == 25
    assert config.api_budget_usd == Decimal("0.50")
    assert config.paid_enabled
    assert config.openai_api_key is not None
    assert config.openai_api_key.get_secret_value() == sentinel
    assert all(
        sentinel not in surface and "openai_api_key" not in surface
        for surface in (
            str(config),
            repr(config),
            repr(config.model_dump()),
            config.to_json(),
        )
    )
    restored = RunConfig.from_json(config.to_json())
    assert restored.model_dump() == config.model_dump()
    assert restored.openai_api_key is None
    assert not restored.paid_enabled
    serialized = pickle.dumps(config)
    assert sentinel.encode("utf-8") not in serialized
    restored_pickle = pickle.loads(serialized)
    assert isinstance(restored_pickle, RunConfig)
    assert restored_pickle.openai_api_key is None


def test_environment_key_overrides_dotenv_even_when_blank(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENAI_API_KEY=dotenv-key\n", encoding="utf-8")
    config = load_config(
        environ={**LIVE_SETTINGS, "OPENAI_API_KEY": "environment-key"},
        dotenv_path=dotenv,
    )
    assert config.openai_api_key is not None
    assert config.openai_api_key.get_secret_value() == "environment-key"
    with pytest.raises(ConfigError, match="OPENAI_API_KEY is required"):
        load_config(
            environ={**LIVE_SETTINGS, "OPENAI_API_KEY": " "}, dotenv_path=dotenv
        )


def test_environment_limit_and_blank_credentials(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    config = load_config(environ={"AI4ALGEBRA_MAX_STEPS": "99"}, dotenv_path=dotenv)
    assert config.limits.max_steps == 99
    with pytest.raises(ConfigError, match="OPENAI_API_KEY is required"):
        load_config(environ=LIVE_SETTINGS, dotenv_path=dotenv)


@pytest.mark.parametrize(
    "overrides",
    [
        {"AI4ALGEBRA_ALLOW_PAID_API": "false"},
        {"AI4ALGEBRA_API_BUDGET_USD": "0.00"},
        {"AI4ALGEBRA_LLM_PROVIDER": "deterministic"},
    ],
)
def test_disabled_paid_requests_need_no_key(
    tmp_path: Path, overrides: dict[str, str]
) -> None:
    config = load_config(
        environ=LIVE_SETTINGS | overrides, dotenv_path=tmp_path / ".env"
    )
    assert not config.paid_enabled
    if "AI4ALGEBRA_API_BUDGET_USD" in overrides:
        assert config.api_budget_usd == Decimal("0")


@pytest.mark.parametrize(
    "budget", ["NaN", "sNaN", "Infinity", "-0.01", _OVER_BUDGET, "", "hello"]
)
def test_reject_invalid_budget(tmp_path: Path, budget: str) -> None:
    with pytest.raises(ConfigError, match="api_budget_usd"):
        load_config(
            environ={"AI4ALGEBRA_API_BUDGET_USD": budget}, dotenv_path=tmp_path / ".env"
        )


def test_json_config_budget_is_compared_without_rounding(tmp_path: Path) -> None:
    settings = tmp_path / "run.json"
    settings.write_text(f'{{"api_budget_usd":{_OVER_BUDGET}}}', encoding="utf-8")
    with pytest.raises(ConfigError, match=r"between USD 0 and USD 0\.50"):
        load_config(settings, environ={}, dotenv_path=tmp_path / ".env")


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AI4ALGEBRA_MAX_DEPTH", "0"),
        ("AI4ALGEBRA_MAX_NODES", "-1"),
        ("AI4ALGEBRA_MAX_CANDIDATES", "0"),
        ("AI4ALGEBRA_MAX_STEPS", "0"),
        ("AI4ALGEBRA_STEP_TIMEOUT_SECONDS", "0"),
        ("AI4ALGEBRA_TASK_TIMEOUT_SECONDS", "inf"),
        ("AI4ALGEBRA_MAX_INPUT_TOKENS", "0"),
        ("AI4ALGEBRA_MAX_OUTPUT_TOKENS", "1.5"),
    ],
)
def test_reject_nonpositive_or_nonfinite_limits(
    tmp_path: Path, key: str, value: str
) -> None:
    with pytest.raises(ConfigError):
        load_config(environ={key: value}, dotenv_path=tmp_path / ".env")


@pytest.mark.parametrize(
    "settings",
    [
        {"AI4ALGEBRA_LLM_PROVIDER": "unknown"},
        {"AI4ALGEBRA_LLM_MODEL": "alternate-model"},
        {"AI4ALGEBRA_LLM_BASE_URL": "https://example.invalid/v1"},
        {"AI4ALGEBRA_LLM_REASONING_EFFORT": "low"},
        {"AI4ALGEBRA_ALLOW_PAID_API": "yes"},
    ],
)
def test_reject_unapproved_provider_settings(
    tmp_path: Path, settings: dict[str, str]
) -> None:
    with pytest.raises(ConfigError):
        load_config(environ=settings, dotenv_path=tmp_path / ".env")


def test_reject_credentials_in_config_and_redact_validation_errors(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "run.json"
    sentinel = "credential-sentinel"
    settings.write_text(
        json.dumps({"openai_api_key": sentinel, "model": sentinel}), encoding="utf-8"
    )
    with pytest.raises(ConfigError) as caught:
        load_config(
            settings, {"OPENAI_API_KEY": sentinel}, dotenv_path=tmp_path / ".env"
        )
    assert sentinel not in str(caught.value)
    assert "model" in str(caught.value)


def test_reject_invalid_direct_limit_and_budget_values() -> None:
    with pytest.raises(ValidationError):
        Limits.model_validate({"max_steps": True})
    with pytest.raises(ValidationError):
        RunConfig(api_budget_usd=Decimal("NaN"))
    with pytest.raises(ValidationError, match="api_budget_usd"):
        RunConfig(api_budget_usd=Decimal(_OVER_BUDGET))


def test_wire_budget_requires_a_decimal_string_without_rounding() -> None:
    wire = RunConfig().to_json()
    with pytest.raises(ValidationError, match="decimal string"):
        RunConfig.from_json(wire.replace('"0.50"', _OVER_BUDGET))
    with pytest.raises(ValidationError, match=r"between USD 0 and USD 0\.50"):
        RunConfig.from_json(wire.replace('"0.50"', f'"{_OVER_BUDGET}"'))
    exact = "0.4999999999999999999999999999999999999"
    assert RunConfig.from_json(
        wire.replace('"0.50"', f'"{exact}"')
    ).api_budget_usd == Decimal(exact)
