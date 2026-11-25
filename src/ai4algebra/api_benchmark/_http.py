"""Bounded GET requests without redirects or application credentials."""

import re
from dataclasses import dataclass
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from socket import SHUT_RDWR, socket
from threading import Timer
from time import monotonic
from typing import Literal, Protocol
from urllib.parse import urlsplit

TransportFailure = Literal["timeout", "network_error", "response_too_large"]


@dataclass(frozen=True)
class HttpResponse:
    status: int
    mime_type: str | None
    body: bytes


class RequestFailure(Exception):
    def __init__(
        self,
        status: TransportFailure,
        http_status: int | None = None,
        mime_type: str | None = None,
    ) -> None:
        super().__init__(status)
        self.status = status
        self.http_status = http_status
        self.mime_type = mime_type


class HttpTransport(Protocol):
    def get(
        self, url: str, *, timeout_seconds: float, max_response_bytes: int
    ) -> HttpResponse: ...


def media_type(header: str | None) -> str | None:
    if header is None:
        return None
    value = header.split(";", 1)[0].strip().lower()
    if len(value) <= 128 and re.fullmatch(
        r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", value
    ):
        return value
    return None


def _interrupt(sock: socket) -> None:
    try:
        sock.shutdown(SHUT_RDWR)
    except OSError:
        pass


class DirectHttpTransport:
    def get(
        self, url: str, *, timeout_seconds: float, max_response_bytes: int
    ) -> HttpResponse:
        parts = urlsplit(url)
        connection_type = HTTPSConnection if parts.scheme == "https" else HTTPConnection
        connection = connection_type(parts.netloc, timeout=timeout_seconds)
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        deadline = monotonic() + timeout_seconds
        timer: Timer | None = None
        status: int | None = None
        mime: str | None = None
        try:
            connection.connect()
            remaining = deadline - monotonic()
            sock = connection.sock
            if remaining <= 0:
                raise TimeoutError
            if sock is None:
                raise OSError
            sock.settimeout(remaining)
            # Interrupt slow-drip responses as well as idle reads.
            timer = Timer(remaining, _interrupt, (sock,))
            timer.daemon = True
            timer.start()
            connection.request(
                "GET",
                target,
                headers={
                    "Accept": "application/json, text/html",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "User-Agent": "AI4Algebra-Retrieval-Benchmark/1.0",
                },
            )
            with connection.getresponse() as response:
                status = response.status
                mime = media_type(response.getheader("Content-Type"))
                if not 200 <= status < 300:
                    return HttpResponse(status, mime, b"")
                declared_length = response.length
                if declared_length is not None and declared_length > max_response_bytes:
                    raise RequestFailure("response_too_large", status, mime)
                body = response.read(max_response_bytes + 1)
                if monotonic() >= deadline:
                    raise TimeoutError
                if len(body) > max_response_bytes:
                    raise RequestFailure("response_too_large", status, mime)
                if declared_length is not None and len(body) != declared_length:
                    raise OSError
                return HttpResponse(status, mime, body)
        except (OSError, HTTPException, ValueError) as error:
            reason: TransportFailure = (
                "timeout"
                if isinstance(error, TimeoutError) or monotonic() >= deadline
                else "network_error"
            )
            raise RequestFailure(reason, status, mime) from None
        finally:
            if timer is not None:
                timer.cancel()
            connection.close()
