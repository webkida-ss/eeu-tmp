from __future__ import annotations

import re
import unittest

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class CorrelationIdMiddlewareTests(unittest.TestCase):
    def setUp(self) -> None:
        from middleware.correlation import CorrelationIdMiddleware

        app = FastAPI()
        app.add_middleware(CorrelationIdMiddleware)

        @app.get("/normal")
        def normal() -> dict[str, str]:
            return {"status": "ok"}

        @app.get("/state")
        def state(request: Request) -> dict[str, str]:
            return {"correlation_id": request.state.correlation_id}

        @app.get("/error")
        def error() -> None:
            raise HTTPException(status_code=418, detail="handled")

        @app.get("/validated")
        def validated(limit: int) -> dict[str, int]:
            return {"limit": limit}

        self.client = TestClient(app)

    def test_generates_id_when_header_is_missing(self) -> None:
        response = self.client.get("/normal")

        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.headers["X-Correlation-ID"], UUID_PATTERN)

    def test_propagates_safe_incoming_id_to_state_and_response(self) -> None:
        correlation_id = "request-123:child_4.5"

        response = self.client.get("/state", headers={"X-Correlation-ID": correlation_id})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["correlation_id"], correlation_id)
        self.assertEqual(response.headers["X-Correlation-ID"], correlation_id)

    def test_replaces_invalid_incoming_id_without_leaking_it(self) -> None:
        invalid_id = "unsafe value"

        response = self.client.get("/state", headers={"X-Correlation-ID": invalid_id})

        correlation_id = response.headers["X-Correlation-ID"]
        self.assertRegex(correlation_id, UUID_PATTERN)
        self.assertNotIn("unsafe", correlation_id)
        self.assertEqual(response.json()["correlation_id"], correlation_id)

    def test_adds_id_to_handled_error_response(self) -> None:
        response = self.client.get("/error")

        self.assertEqual(response.status_code, 418)
        self.assertRegex(response.headers["X-Correlation-ID"], UUID_PATTERN)

    def test_adds_id_to_validation_error_and_not_found_responses(self) -> None:
        validation_response = self.client.get("/validated?limit=not-an-integer")
        not_found_response = self.client.get("/missing")

        self.assertEqual(validation_response.status_code, 422)
        self.assertRegex(validation_response.headers["X-Correlation-ID"], UUID_PATTERN)
        self.assertEqual(not_found_response.status_code, 404)
        self.assertRegex(not_found_response.headers["X-Correlation-ID"], UUID_PATTERN)


class MainAppCorrelationTests(unittest.TestCase):
    def test_main_app_installs_correlation_middleware(self) -> None:
        from main import app

        response = TestClient(app).get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.headers["X-Correlation-ID"], UUID_PATTERN)

    def test_cors_preflight_keeps_extension_origin_and_correlation_id(self) -> None:
        from main import app

        response = TestClient(app).options(
            "/health",
            headers={
                "Origin": "chrome-extension://abcdefghijklmnop",
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"],
            "chrome-extension://abcdefghijklmnop",
        )
        self.assertRegex(response.headers["X-Correlation-ID"], UUID_PATTERN)


if __name__ == "__main__":
    unittest.main()
