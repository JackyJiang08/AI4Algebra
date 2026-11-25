from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

import pytest

from ai4algebra.api_benchmark._http import DirectHttpTransport, RequestFailure


def test_http_transport_disallows_redirects_and_bounds_responses() -> None:
    paths: list[str] = []
    release = Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            paths.append(self.path)
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/redirect-target")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            if self.path == "/large-length":
                self.send_header("Content-Length", "100")
            if self.path == "/slow":
                self.send_header("Content-Length", "10")
            self.end_headers()
            if self.path == "/large-stream":
                self.wfile.write(b"x" * 33)
            if self.path == "/slow":
                release.wait(5)

        def log_message(self, format: str, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        listener = Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        listener.start()
        transport = DirectHttpTransport()
        origin = f"http://127.0.0.1:{server.server_port}"
        try:
            redirect = transport.get(
                origin + "/redirect", timeout_seconds=2, max_response_bytes=32
            )
            assert redirect.status == 302 and redirect.body == b""
            for route in ("/large-length", "/large-stream"):
                with pytest.raises(RequestFailure) as cap:
                    transport.get(
                        origin + route, timeout_seconds=2, max_response_bytes=32
                    )
                assert cap.value.status == "response_too_large"
                assert cap.value.http_status == 200
                assert cap.value.mime_type == "application/json"
            with pytest.raises(RequestFailure) as timeout:
                transport.get(
                    origin + "/slow", timeout_seconds=0.25, max_response_bytes=32
                )
            assert timeout.value.status == "timeout"
        finally:
            release.set()
            server.shutdown()
            listener.join(timeout=2)
    assert paths == ["/redirect", "/large-length", "/large-stream", "/slow"]
