"""Settings for the standalone, keyless retrieval benchmark."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import ip_address
from math import isfinite
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import dotenv_values


class BenchmarkConfigError(ValueError):
    """Invalid local benchmark inputs."""


_DEFAULTS = {
    "STACKS_BASE_URL": "https://stacks.math.columbia.edu",
    "LEANEXPLORE_BASE_URL": "https://www.leanexplore.com/api/v2",
    "LOOGLE_BASE_URL": "https://loogle.lean-lang.org",
    "STACKS_API_ENABLED": "false",
    "API_TIMEOUT_SECONDS": "20",
    "API_MAX_RESPONSE_BYTES": "1048576",
    "API_RESULT_LIMIT": "5",
    "API_REQUEST_INTERVAL_SECONDS": "1.0",
}


@dataclass(frozen=True)
class BenchmarkSettings:
    stacks_base_url: str = _DEFAULTS["STACKS_BASE_URL"]
    leanexplore_base_url: str = _DEFAULTS["LEANEXPLORE_BASE_URL"]
    loogle_base_url: str = _DEFAULTS["LOOGLE_BASE_URL"]
    stacks_enabled: bool = False
    timeout_seconds: float = 20
    max_response_bytes: int = 1_048_576
    result_limit: int = 5
    request_interval_seconds: float = 1.0

    def base_url(self, service: Literal["stacks", "leanexplore", "loogle"]) -> str:
        return {
            "stacks": self.stacks_base_url,
            "leanexplore": self.leanexplore_base_url,
            "loogle": self.loogle_base_url,
        }[service]


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _base_url(value: str, key: str) -> str:
    error = BenchmarkConfigError(
        f"AI4ALGEBRA_{key} must be an HTTPS base URL or a loopback HTTP base URL"
        " without credentials, a query, or a fragment"
    )
    if any(char.isspace() or not char.isprintable() for char in value):
        raise error
    if any(char in value for char in "@?#\\"):
        raise error
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise error from None
    if (
        not host
        or not value.isascii()
        or "%" in parts.netloc
        or port == 0
        or (parts.scheme != "https" and (parts.scheme != "http" or not _loopback(host)))
    ):
        raise error
    return value.rstrip("/")


def _integer(value: str, key: str, maximum: int) -> int:
    error = BenchmarkConfigError(
        f"AI4ALGEBRA_{key} must be an integer from 1 to {maximum}"
    )
    try:
        number = int(value)
    except ValueError:
        raise error from None
    if not 1 <= number <= maximum:
        raise error
    return number


def _seconds(value: str, key: str, minimum: float, maximum: float) -> float:
    error = BenchmarkConfigError(
        f"AI4ALGEBRA_{key} must be between {minimum:g} and {maximum:g}"
    )
    try:
        number = float(value)
    except ValueError:
        raise error from None
    if not isfinite(number) or not minimum <= number <= maximum:
        raise error
    return number


def load_settings(
    dotenv_path: Path = Path(".env"), *, environ: Mapping[str, str] | None = None
) -> BenchmarkSettings:
    """Read only benchmark settings. Process environment values take precedence."""
    try:
        dotenv = dotenv_values(dotenv_path, interpolate=False, encoding="utf-8-sig")
    except (OSError, ValueError):
        raise BenchmarkConfigError("could not read benchmark dotenv settings") from None
    environment = os.environ if environ is None else environ
    values = {}
    for suffix, default in _DEFAULTS.items():
        key = f"AI4ALGEBRA_{suffix}"
        value = environment.get(key, dotenv.get(key))
        values[suffix] = default if value is None else value

    enabled = values["STACKS_API_ENABLED"].strip().lower()
    if enabled not in {"true", "false"}:
        raise BenchmarkConfigError(
            "AI4ALGEBRA_STACKS_API_ENABLED must be true or false"
        )
    return BenchmarkSettings(
        stacks_base_url=_base_url(values["STACKS_BASE_URL"], "STACKS_BASE_URL"),
        leanexplore_base_url=_base_url(
            values["LEANEXPLORE_BASE_URL"], "LEANEXPLORE_BASE_URL"
        ),
        loogle_base_url=_base_url(values["LOOGLE_BASE_URL"], "LOOGLE_BASE_URL"),
        stacks_enabled=enabled == "true",
        timeout_seconds=_seconds(
            values["API_TIMEOUT_SECONDS"], "API_TIMEOUT_SECONDS", 0.01, 120
        ),
        max_response_bytes=_integer(
            values["API_MAX_RESPONSE_BYTES"], "API_MAX_RESPONSE_BYTES", 16_777_216
        ),
        result_limit=_integer(values["API_RESULT_LIMIT"], "API_RESULT_LIMIT", 100),
        request_interval_seconds=_seconds(
            values["API_REQUEST_INTERVAL_SECONDS"],
            "API_REQUEST_INTERVAL_SECONDS",
            0,
            120,
        ),
    )
