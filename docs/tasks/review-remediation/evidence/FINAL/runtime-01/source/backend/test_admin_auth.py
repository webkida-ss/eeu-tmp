from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from accounts import User
from config import ADMIN_ENABLED
from deps import get_current_user
from fastapi.testclient import TestClient
from generated.admin_models import AdminSession, CorrelationError
from main import app
from openapi_contract_support import ContractRequest, ContractResponse, openapi_from_bundle
from services.admin_auth import AdminForbidden, require_admin

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "schema"))
from schema_tasks import redocly_bundle  # noqa: E402

ADMIN = User(id="admin-1", email=" Admin@Example.COM ", display_name="Admin")
LEARNER = User(id="learner-1", email="learner@example.com", display_name="Learner")


@pytest.mark.parametrize(
    "allowlist",
    [
        ("admin@example.com",),
        (" ADMIN@EXAMPLE.COM ",),
    ],
)
def test_require_admin_normalizes_email_for_exact_match(
    allowlist: tuple[str, ...],
) -> None:
    assert require_admin(ADMIN, allowlist) is ADMIN


@pytest.mark.parametrize("allowlist", [(), ("",), ("other@example.com",), ("*",)])
def test_require_admin_fails_closed_without_exact_allowlist_match(
    allowlist: tuple[str, ...],
) -> None:
    with pytest.raises(AdminForbidden):
        require_admin(ADMIN, allowlist)


def test_require_admin_rejects_missing_user_email() -> None:
    user = User(id="admin-1", email="", display_name="Admin")

    with pytest.raises(AdminForbidden):
        require_admin(user, ("admin@example.com",))


@pytest.fixture
def client() -> TestClient:
    if not ADMIN_ENABLED:
        pytest.skip("local admin API is disabled")
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_admin_session_returns_generated_schema_for_allowlisted_user(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: ADMIN

    with patch("admin.deps.ADMIN_EMAILS", ("admin@example.com",)):
        response = client.get("/admin/v1/session", headers={"X-Correlation-ID": "admin-session-1"})

    assert response.status_code == 200
    session = AdminSession.model_validate(response.json())
    assert session.user_id == ADMIN.id
    assert session.email == "admin@example.com"
    assert response.headers["X-Correlation-ID"] == "admin-session-1"


def test_admin_session_maps_missing_authentication_to_schema_error(
    client: TestClient,
) -> None:
    response = client.get("/admin/v1/session", headers={"X-Correlation-ID": "admin-session-401"})

    assert response.status_code == 401
    error = CorrelationError.model_validate(response.json())
    assert error.code == "unauthenticated"
    assert error.correlation_id == "admin-session-401"
    assert response.headers["X-Correlation-ID"] == error.correlation_id


def test_admin_session_rejects_non_allowlisted_user_on_every_request(
    client: TestClient,
) -> None:
    app.dependency_overrides[get_current_user] = lambda: LEARNER

    with patch("admin.deps.ADMIN_EMAILS", ("admin@example.com",)):
        first = client.get("/admin/v1/session", headers={"X-Correlation-ID": "admin-session-403-a"})
    with patch("admin.deps.ADMIN_EMAILS", ("learner@example.com",)):
        second = client.get(
            "/admin/v1/session", headers={"X-Correlation-ID": "admin-session-403-b"}
        )

    assert first.status_code == 403
    error = CorrelationError.model_validate(first.json())
    assert error.code == "admin_forbidden"
    assert error.correlation_id == "admin-session-403-a"
    assert second.status_code == 200


def test_only_admin_session_route_is_mounted(client: TestClient) -> None:
    admin_routes = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/admin/")
        for method in operations
    }

    assert admin_routes == {("GET", "/admin/v1/session")}


def test_admin_session_canonical_contract(client: TestClient) -> None:
    contract = openapi_from_bundle(redocly_bundle())
    request = ContractRequest(
        method="get",
        url="http://127.0.0.1:18765/admin/v1/session",
        headers={"Authorization": "Bearer local-test-token"},
    )
    for user, expected_status in [(None, 401), (LEARNER, 403), (ADMIN, 200)]:
        app.dependency_overrides.clear()
        if user is not None:
            app.dependency_overrides[get_current_user] = lambda user=user: user
        with patch("admin.deps.ADMIN_EMAILS", ("admin@example.com",)):
            response = client.get("/admin/v1/session")
        assert response.status_code == expected_status
        contract.validate_response(
            request,
            ContractResponse(response.status_code, response.content, dict(response.headers)),
        )
