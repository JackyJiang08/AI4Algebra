"""Single-attempt OpenAI HTTPS transport with bounded response and cancellation."""

import http.client
import socket
import time
from dataclasses import dataclass
from threading import Event, Thread
from typing import Literal, Protocol

from pydantic import SecretStr

Endpoint = Literal["/responses/input_tokens", "/responses"]
MAX_RESPONSE_BYTES = 1_048_576


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes


class TransportError(RuntimeError):
    def __init__(
        self, status: Literal["timeout", "cancelled", "unavailable", "malformed"]
    ) -> None:
        super().__init__(status)
        self.status = status


class ResponsesTransport(Protocol):
    def post(
        self,
        endpoint: Endpoint,
        payload: bytes,
        *,
        key: SecretStr,
        timeout_seconds: float,
        cancelled: Event | None,
    ) -> HttpResponse: ...


class OpenAIHTTPS:
    def post(
        self,
        endpoint: Endpoint,
        payload: bytes,
        *,
        key: SecretStr,
        timeout_seconds: float,
        cancelled: Event | None,
    ) -> HttpResponse:
        if endpoint not in ("/responses/input_tokens", "/responses"):
            raise TransportError("unavailable")
        if cancelled is not None and cancelled.is_set():
            raise TransportError("cancelled")
        if timeout_seconds <= 0:
            raise TransportError("timeout")
        # http.client does not follow redirects or retry credentials on another origin.
        connection = http.client.HTTPSConnection(
            "api.openai.com", timeout=timeout_seconds
        )
        deadline = time.monotonic() + timeout_seconds
        done = Event()
        stop = Event()
        result: HttpResponse | None = None
        failure: Literal["timeout", "cancelled", "unavailable", "malformed"] = (
            "unavailable"
        )

        def request() -> None:
            nonlocal result, failure
            try:
                if stop.is_set() or (cancelled is not None and cancelled.is_set()):
                    failure = "cancelled"
                    return
                # DNS/TLS connection setup can outlive the caller's wait. Complete it
                # separately and recheck before transmitting credentials or payload.
                connection.connect()
                remaining = deadline - time.monotonic()
                if stop.is_set() or (cancelled is not None and cancelled.is_set()):
                    failure = "cancelled"
                    return
                if remaining <= 0:
                    failure = "timeout"
                    return
                connection.timeout = remaining
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                connection.request(
                    "POST",
                    "/v1" + endpoint,
                    body=payload,
                    headers={
                        "Authorization": "Bearer " + key.get_secret_value(),
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                with connection.getresponse() as response:
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(body) > MAX_RESPONSE_BYTES:
                        failure = "malformed"
                    else:
                        result = HttpResponse(response.status, body)
            except TimeoutError:
                failure = "timeout"
            except (OSError, ValueError, http.client.HTTPException):
                failure = "unavailable"
            finally:
                connection.close()
                done.set()

        thread = Thread(target=request, daemon=True, name="openai-responses-request")
        thread.start()
        while not done.is_set():
            remaining = deadline - time.monotonic()
            abort = cancelled is not None and cancelled.is_set()
            if abort or remaining <= 0:
                stop.set()
                active_socket = connection.sock
                if active_socket is not None:
                    try:
                        active_socket.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                raise TransportError("cancelled" if abort else "timeout")
            done.wait(min(remaining, 0.05))
        if result is None:
            raise TransportError(failure)
        return result
