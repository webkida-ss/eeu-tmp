from __future__ import annotations

import importlib.util
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).parent / "scripts" / "check_health.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("check_health", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load health checker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SequencedHealthHandler(BaseHTTPRequestHandler):
    responses: list[tuple[int, bytes]] = []
    request_paths: list[str] = []

    def do_GET(self) -> None:
        type(self).request_paths.append(self.path)
        status, body = type(self).responses.pop(0)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


@contextmanager
def health_server(
    responses: list[tuple[int, dict[str, object] | bytes]],
) -> Iterator[str]:
    SequencedHealthHandler.responses = [
        (
            status,
            json.dumps(body).encode("utf-8") if isinstance(body, dict) else body,
        )
        for status, body in responses
    ]
    SequencedHealthHandler.request_paths = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), SequencedHealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_wait_for_health_accepts_exact_ok_payload() -> None:
    checker = load_checker()
    with health_server([(200, {"status": "ok"})]) as endpoint:
        attempts_used = checker.wait_for_health(
            endpoint,
            attempts=1,
            delay_seconds=0,
            timeout_seconds=1,
        )

    assert attempts_used == 1
    assert SequencedHealthHandler.request_paths == ["/health"]


def test_wait_for_health_retries_transient_http_failure() -> None:
    checker = load_checker()
    sleeps: list[float] = []
    with health_server([(503, {"status": "starting"}), (200, {"status": "ok"})]) as endpoint:
        attempts_used = checker.wait_for_health(
            endpoint,
            attempts=2,
            delay_seconds=0.25,
            timeout_seconds=1,
            sleep=sleeps.append,
        )

    assert attempts_used == 2
    assert sleeps == [0.25]
    assert SequencedHealthHandler.request_paths == ["/health", "/health"]


def test_wait_for_health_fails_after_invalid_payloads() -> None:
    checker = load_checker()
    with health_server([(200, b"not-json"), (200, {"status": "degraded"})]) as endpoint:
        with pytest.raises(checker.HealthCheckError, match="after 2 attempts"):
            checker.wait_for_health(
                endpoint,
                attempts=2,
                delay_seconds=0,
                timeout_seconds=1,
                sleep=lambda _: None,
            )

    assert len(SequencedHealthHandler.request_paths) == 2


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("https://api.example.com", "https://api.example.com/health"),
        ("https://api.example.com/", "https://api.example.com/health"),
        ("https://api.example.com/prod", "https://api.example.com/prod/health"),
        (
            "https://api.example.com/prod/health",
            "https://api.example.com/prod/health",
        ),
    ],
)
def test_build_health_url_appends_health_exactly_once(
    endpoint: str,
    expected: str,
) -> None:
    checker = load_checker()
    assert checker.build_health_url(endpoint) == expected


@pytest.mark.parametrize(
    "endpoint",
    [
        "api.example.com",
        "ftp://api.example.com",
        "https://api.example.com?token=secret",
        "https://api.example.com#health",
        "https://user:secret@api.example.com",
    ],
)
def test_build_health_url_rejects_invalid_endpoints(endpoint: str) -> None:
    checker = load_checker()
    with pytest.raises(checker.HealthCheckError):
        checker.build_health_url(endpoint)
