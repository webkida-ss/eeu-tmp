#!/usr/bin/env python3
"""Wait for the deployed Untangle backend health endpoint."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


class HealthCheckError(RuntimeError):
    """Raised when a backend endpoint is invalid or remains unhealthy."""


def build_health_url(api_endpoint: str) -> str:
    raw_endpoint = api_endpoint.strip()
    try:
        parsed = urlsplit(raw_endpoint)
        _ = parsed.port
    except ValueError as error:
        raise HealthCheckError("API endpoint is invalid") from error

    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HealthCheckError("API endpoint must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise HealthCheckError("API endpoint must not contain credentials")
    if parsed.query or parsed.fragment:
        raise HealthCheckError("API endpoint must not contain a query or fragment")

    path = parsed.path.rstrip("/")
    if not path.endswith("/health"):
        path = f"{path}/health"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def wait_for_health(
    api_endpoint: str,
    *,
    attempts: int,
    delay_seconds: float,
    timeout_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    if attempts < 1:
        raise HealthCheckError("attempts must be at least 1")
    if delay_seconds < 0:
        raise HealthCheckError("delay seconds must not be negative")
    if timeout_seconds <= 0:
        raise HealthCheckError("timeout seconds must be greater than 0")

    health_url = build_health_url(api_endpoint)
    for attempt in range(1, attempts + 1):
        try:
            request = Request(
                health_url,
                headers={"User-Agent": "untangle-deployment-health-check/1"},
            )
            with urlopen(request, timeout=timeout_seconds) as response:
                if not 200 <= response.status < 300:
                    raise HealthCheckError("health endpoint returned a non-2xx status")
                payload = json.loads(response.read(1024).decode("utf-8"))
            if payload != {"status": "ok"}:
                raise HealthCheckError("health endpoint returned an unexpected payload")
            print(f"health check passed on attempt {attempt}: {health_url}")
            return attempt
        except (
            HealthCheckError,
            HTTPError,
            URLError,
            TimeoutError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            print(
                f"health check attempt {attempt}/{attempts} failed: {type(error).__name__}",
                file=sys.stderr,
            )
            if attempt < attempts:
                sleep(delay_seconds)

    raise HealthCheckError(f"backend remained unhealthy after {attempts} attempts")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wait for the deployed Untangle backend to become healthy."
    )
    parser.add_argument("--api-endpoint", required=True)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--delay-seconds", type=float, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=10)
    return parser.parse_args()


def main() -> int:
    arguments = parse_arguments()
    try:
        wait_for_health(
            arguments.api_endpoint,
            attempts=arguments.attempts,
            delay_seconds=arguments.delay_seconds,
            timeout_seconds=arguments.timeout_seconds,
        )
    except HealthCheckError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
