"""Transport invariants executed in separate disabled/enabled Task processes."""

import pytest
from config import ADMIN_ALLOWED_ORIGIN, ADMIN_ENABLED
from deps import get_current_user
from fastapi import HTTPException
from fastapi.testclient import TestClient
from main import app
from middleware.cors import RouteCorsMiddleware
from schemas import ApiError


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.test",
        "https://user:password@example.test",
        "null",
        "https://example.test/path",
        "https://example.test?query=1",
    ],
)
def test_admin_origin_configuration_fails_closed(origin):
    with pytest.raises(ValueError, match="exact HTTP origin"):
        RouteCorsMiddleware(app, learner_origins=[], admin_origin=origin)


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_learner_unauthenticated_error_keeps_api_error_contract(client):
    response = client.get("/pages/preload?page_url=https://example.test/article")
    assert response.status_code == 401
    assert ApiError.model_validate(response.json()).detail
    assert "message" not in response.json()


def test_learner_suspension_keeps_api_error_contract(client):
    def suspended_user():
        raise HTTPException(
            403, detail={"code": "account_suspended", "message": "Account is suspended."}
        )

    app.dependency_overrides[get_current_user] = suspended_user
    response = client.get("/pages/preload?page_url=https://example.test/article")
    assert response.status_code == 403
    assert ApiError.model_validate(response.json()).detail == "Account is suspended."
    assert response.json()["code"] == "account_suspended"


def test_admin_route_availability_matches_flag(client):
    response = client.get("/admin/v1/session")
    assert response.status_code == (401 if ADMIN_ENABLED else 404)


@pytest.mark.parametrize("header", ["Authorization", "authorization, X-Correlation-ID"])
def test_admin_preflight_accepts_only_configured_origin(client, header):
    for origin, expected in [
        (ADMIN_ALLOWED_ORIGIN, 200),
        ("chrome-extension://abcdefghijklmnop", 400),
        ("https://untrusted.example.test", 400),
    ]:
        response = client.options(
            "/admin/v1/session",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": header,
            },
        )
        assert response.status_code == expected
        assert response.headers.get("access-control-allow-origin") == (
            ADMIN_ALLOWED_ORIGIN if expected == 200 else None
        )


def test_admin_preflight_rejects_unapproved_header(client):
    response = client.options(
        "/admin/v1/session",
        headers={
            "Origin": ADMIN_ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Unapproved-Header",
        },
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "origin", ["chrome-extension://abcdefghijklmnop", "https://untrusted.example.test"]
)
def test_admin_error_does_not_allow_unapproved_origin(client, origin):
    response = client.get("/admin/v1/session", headers={"Origin": origin})
    assert "access-control-allow-origin" not in response.headers


def test_admin_error_allows_configured_origin_and_exposes_correlation(client):
    response = client.get("/admin/v1/session", headers={"Origin": ADMIN_ALLOWED_ORIGIN})
    assert response.headers["access-control-allow-origin"] == ADMIN_ALLOWED_ORIGIN
    assert response.headers["access-control-expose-headers"] == "X-Correlation-ID"


def test_learner_preflight_preserves_extension_access(client):
    origin = "chrome-extension://abcdefghijklmnop"
    response = client.options(
        "/pages/preload",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
