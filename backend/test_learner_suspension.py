from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
import schemas
from accounts import User
from config import ADMIN_ENABLED
from deps import (
    get_active_learner_user,
    get_admin_account_control_repository,
    get_current_user,
)
from fastapi.testclient import TestClient
from generated.admin_models import AdminSession
from main import app
from repositories.memory_admin_account_control import (
    MemoryAdminAccountControlRepository,
)
from services.account_access import AccountSuspended, require_active_learner

SUSPENDED_USER = User(
    id="suspended-1",
    email="admin@example.com",
    display_name="Suspended Admin",
)


def suspended_repository() -> MemoryAdminAccountControlRepository:
    repository = MemoryAdminAccountControlRepository()
    repository.transition(
        target_user_id=SUSPENDED_USER.id,
        desired_status="suspended",
        actor_user_id="admin-2",
        actor_email="admin-2@example.com",
        reason="Policy review",
        correlation_id="suspension-test",
        occurred_at=datetime(2026, 7, 20, tzinfo=UTC),
        audit_id=schemas.generate_uuid7(),
    )
    return repository


def test_require_active_learner_rejects_suspended_account() -> None:
    with pytest.raises(AccountSuspended) as error:
        require_active_learner(SUSPENDED_USER.id, suspended_repository())

    assert error.value.code == "account_suspended"


def test_require_active_learner_allows_active_account() -> None:
    repository = MemoryAdminAccountControlRepository()

    assert require_active_learner("active-1", repository) is None


@pytest.fixture
def client() -> TestClient:
    repository = suspended_repository()
    app.dependency_overrides[get_current_user] = lambda: SUSPENDED_USER
    app.dependency_overrides[get_admin_account_control_repository] = lambda: repository
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("method", "path", "json"),
    [
        ("get", "/pages/preload?page_url=https://example.com/article", None),
        ("post", "/pages/preload", {}),
        ("get", "/vocabulary", None),
        ("post", "/analyze", {}),
        ("post", "/chat", {}),
        ("get", "/phrases", None),
        ("post", "/phrases", {}),
        ("get", "/billing/me", None),
        ("post", "/billing/checkout", {}),
        ("post", "/billing/portal", None),
    ],
)
def test_suspended_account_is_rejected_from_every_learner_product_surface(
    client: TestClient,
    method: str,
    path: str,
    json: dict[str, object] | None,
) -> None:
    response = client.request(
        method,
        path,
        json=json,
        headers={"X-Correlation-ID": "suspended-product"},
    )

    assert response.status_code == 403, (method, path, response.text)
    error = schemas.ApiError.model_validate(response.json())
    assert error.code == "account_suspended"
    assert error.detail
    assert response.headers["X-Correlation-ID"] == "suspended-product"


def test_suspended_account_can_still_use_auth_me_and_logout(
    client: TestClient,
) -> None:
    me = client.get("/auth/me")
    logout = client.post("/auth/logout")

    assert me.status_code == 200
    assert me.json()["id"] == SUSPENDED_USER.id
    assert logout.status_code == 200
    assert logout.json() == {"status": "ok"}


@pytest.mark.skipif(not ADMIN_ENABLED, reason="local admin API is disabled")
def test_suspended_allowlisted_admin_can_use_admin_session(
    client: TestClient,
) -> None:
    with patch("admin.deps.ADMIN_EMAILS", ("admin@example.com",)):
        response = client.get("/admin/v1/session")

    assert response.status_code == 200
    assert AdminSession.model_validate(response.json()).user_id == SUSPENDED_USER.id


def test_account_control_unavailability_is_explicit() -> None:
    with patch("deps.ADMIN_ENABLED", False):
        assert (
            get_active_learner_user(
                current_user=SUSPENDED_USER,
                account_repository=None,
            )
            is SUSPENDED_USER
        )

    with patch("deps.ADMIN_ENABLED", True), pytest.raises(RuntimeError):
        get_active_learner_user(
            current_user=SUSPENDED_USER,
            account_repository=None,
        )


def test_learner_response_schemas_are_unchanged() -> None:
    expected = {
        ("GET", "/pages/preload"): "PagePreloadStatusResponse",
        ("POST", "/pages/preload"): "PagePreloadStatusResponse",
        ("GET", "/vocabulary"): "VocabularyBookResponse",
        ("POST", "/analyze"): "AnalyzeResponse",
        ("POST", "/chat"): "ChatResponse",
        ("GET", "/phrases"): "list",
        ("POST", "/phrases"): "PhraseRecord",
        ("GET", "/billing/me"): "BillingMeResponse",
        ("POST", "/billing/checkout"): "CheckoutResponse",
        ("POST", "/billing/portal"): "PortalResponse",
    }
    specification = app.openapi()
    actual = {}
    for method, path in expected:
        operation = specification["paths"][path][method.lower()]
        success_code = "202" if (method, path) == ("POST", "/pages/preload") else "200"
        schema = operation["responses"][success_code]["content"]["application/json"]["schema"]
        reference = schema.get("$ref")
        schema_name = reference.rsplit("/", 1)[-1] if reference else schema.get("type")
        actual[(method, path)] = "list" if schema_name == "array" else schema_name

    assert actual == expected
