from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import deps
import httpx
import pytest
from accounts import BillingError, SubscriptionEvent, User
from accounts.billing import MockBillingProvider
from accounts.ports import ProviderSubscription
from accounts.storage import JsonEmailAuthService, JsonSubscriptionRepository
from accounts.testing import build_test_accounts
from core.plans import PLAN_CATALOG
from fastapi.testclient import TestClient
from main import MAX_WEBHOOK_BODY_BYTES, app
from openapi_contract_support import (
    ContractRequest,
    ContractResponse,
    assert_status_and_media,
    openapi_from_bundle,
)
from repositories.page_preload_repository import JsonPagePreloadRepository
from repositories.phrase_repository import JsonPhraseRepository
from repositories.usage_repository import JsonUsageRepository
from schemas import AnalyzeResponse, ChatResponse, PagePreloadStatusResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "schema"))
from schema_tasks import redocly_bundle  # noqa: E402

UUID7 = "018f47a2-7b3c-7abc-8def-0123456789ab"


class ContractAuthService:
    def __init__(self, user: User) -> None:
        self.user = user

    def login(self, *, email: str, display_name: str | None = None) -> tuple[str, User]:
        return "fake-local-session", self.user

    def resolve_user(self, access_token: str) -> User | None:
        return self.user if access_token else None

    def logout(self, access_token: str) -> None:
        return None


@pytest.fixture(scope="module")
def contract():
    return openapi_from_bundle(redocly_bundle())


@pytest.fixture
def local_api(tmp_path):
    user = User(id=UUID7, email="learner@example.test", display_name="Learner")
    auth = ContractAuthService(user)
    preloads = JsonPagePreloadRepository(tmp_path / "preloads.json")
    phrases = JsonPhraseRepository(tmp_path / "phrases.json")
    subscriptions = JsonSubscriptionRepository(tmp_path / "subscriptions.json")
    usage = JsonUsageRepository(tmp_path / "usage.json")
    accounts = build_test_accounts(
        plans=PLAN_CATALOG,
        auth_service=auth,
        subscription_repository=subscriptions,
        billing_provider=MockBillingProvider(PLAN_CATALOG),
    )
    app.dependency_overrides[deps.get_accounts] = lambda: accounts
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_page_preload_repository] = lambda: preloads
    app.dependency_overrides[deps.get_phrase_repository] = lambda: phrases
    app.dependency_overrides[deps.get_subscription_repository] = lambda: subscriptions
    app.dependency_overrides[deps.get_usage_repository] = lambda: usage
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, subscriptions, accounts
    app.dependency_overrides.clear()


def validate_exchange(
    contract,
    *,
    method: str,
    path: str,
    body,
    response,
    request_media_type: str | None = "application/json",
    auth: str | None = "Bearer fake-local-session",
    extra_headers: dict[str, str] | None = None,
):
    headers = dict(extra_headers or {})
    if auth:
        headers["Authorization"] = auth
    payload = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    if payload is not None and request_media_type:
        headers["Content-Type"] = request_media_type
    request = ContractRequest(
        method=method.lower(),
        url=f"http://127.0.0.1:18765{path}",
        body=payload,
        content_type=request_media_type or "",
        headers=headers,
    )
    contract.validate_request(request)
    media_type = response.headers["content-type"].split(";", 1)[0]
    assert_status_and_media(response, response.status_code, media_type)
    contract.validate_response(
        request,
        ContractResponse(response.status_code, response.content, dict(response.headers)),
    )


def test_create_auth_session(contract, local_api):
    client, _, _ = local_api
    body = {"credential": "mock:learner@example.test:Learner"}
    response = client.post("/auth/login", json=body)
    assert response.status_code == 200
    validate_exchange(
        contract, method="POST", path="/auth/login", body=body, response=response, auth=None
    )

    rejected_body = {"credential": "not-a-provider-token"}
    rejected = client.post("/auth/login", json=rejected_body)
    assert rejected.status_code == 401
    validate_exchange(
        contract,
        method="POST",
        path="/auth/login",
        body=rejected_body,
        response=rejected,
        auth=None,
    )


@pytest.mark.parametrize(
    "authorization",
    [None, "Basic malformed", "Bearer expired-local-session"],
    ids=["missing", "malformed", "expired"],
)
def test_bearer_session_failures(contract, tmp_path, authorization):
    auth = JsonEmailAuthService(tmp_path / "users.json", tmp_path / "sessions.json")
    app.dependency_overrides.clear()
    accounts = build_test_accounts(plans=PLAN_CATALOG, auth_service=auth)
    app.dependency_overrides[deps.get_accounts] = lambda: accounts
    headers = {"Authorization": authorization} if authorization else {}
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/auth/me", headers=headers)
    app.dependency_overrides.clear()
    assert_status_and_media(response, 401, "application/json")
    request = ContractRequest(
        method="get",
        url="http://127.0.0.1:18765/auth/me",
        content_type="",
        headers=headers,
    )
    contract.validate_response(
        request, ContractResponse(response.status_code, response.content, dict(response.headers))
    )


def test_create_page_preload(contract, local_api, monkeypatch):
    client, _, _ = local_api
    monkeypatch.setattr(
        "main.reading.submit_preload",
        lambda *args, **kwargs: PagePreloadStatusResponse(
            ready=False, preload=None, status="processing", error=None
        ),
    )
    body = {
        "operation_id": UUID7,
        "page_url": "https://example.test/article",
        "html": "<article><p>Learning takes practice.</p></article>",
    }
    response = client.post("/pages/preload", json=body, headers={"Authorization": "Bearer fake"})
    assert response.status_code == 202
    validate_exchange(contract, method="POST", path="/pages/preload", body=body, response=response)


def test_analyze_text(contract, local_api, monkeypatch):
    client, _, _ = local_api
    monkeypatch.setattr(
        "main.reading.analyze_selection",
        lambda *args, **kwargs: AnalyzeResponse(
            original_text="Learning takes practice.",
            translation="Learning requires practice.",
        ),
    )
    body = {"operation_id": UUID7, "text": "Learning takes practice."}
    response = client.post("/analyze", json=body, headers={"Authorization": "Bearer fake"})
    assert response.status_code == 200
    validate_exchange(contract, method="POST", path="/analyze", body=body, response=response)


def test_create_chat_reply(contract, local_api, monkeypatch):
    client, _, _ = local_api
    monkeypatch.setattr(
        "main.reading.chat_reply",
        lambda *args, **kwargs: ChatResponse(reply="The present simple states a general truth."),
    )
    body = {
        "operation_id": UUID7,
        "message": "Why is this tense used?",
        "context_label": "sentence",
        "context_text": "Learning takes practice.",
    }
    response = client.post("/chat", json=body, headers={"Authorization": "Bearer fake"})
    assert response.status_code == 200
    validate_exchange(contract, method="POST", path="/chat", body=body, response=response)


def test_create_billing_checkout(contract, local_api):
    client, _, _ = local_api
    body = {"plan": "pro"}
    response = client.post("/billing/checkout", json=body, headers={"Authorization": "Bearer fake"})
    assert response.status_code == 200
    validate_exchange(
        contract, method="POST", path="/billing/checkout", body=body, response=response
    )


def test_open_billing_portal(contract, local_api):
    client, subscriptions, _ = local_api
    subscriptions.upsert(
        UUID7,
        {
            "plan": "pro",
            "status": "active",
            "stripe_customer_id": "mock_customer_local",
        },
    )
    response = client.post("/billing/portal", headers={"Authorization": "Bearer fake"})
    assert response.status_code == 200
    validate_exchange(contract, method="POST", path="/billing/portal", body=None, response=response)


class RecordingWebhookProvider:
    def __init__(self):
        self.calls = []

    def parse_webhook_event(self, payload: bytes, signature: str | None):
        self.calls.append((payload, signature))
        if signature != "t=1700000000,v1=fake-local-signature":
            raise BillingError("Invalid webhook signature.", status_code=400)
        return SubscriptionEvent(
            kind="updated",
            event_id="evt_test_0001",
            user_id=UUID7,
            stripe_customer_id="cus_test_0001",
            data={
                "plan": "pro",
                "status": "active",
                "stripe_subscription_id": "sub_test_0001",
            },
        )

    def retrieve_subscription(self, stripe_subscription_id: str):
        return ProviderSubscription(
            user_id=UUID7,
            stripe_customer_id="cus_test_0001",
            stripe_subscription_id=stripe_subscription_id,
            plan="pro",
            status="active",
            current_period_end=1_900_000_000,
        )


def test_process_billing_webhook(contract, local_api):
    client, _, accounts = local_api
    provider = RecordingWebhookProvider()
    app.dependency_overrides[deps.get_accounts] = lambda: replace(
        accounts,
        billing_provider=provider,
    )
    raw = b'{"id":"evt_test_0001","type":"customer.subscription.updated"}'
    headers = {
        "Content-Type": "application/json",
        "Stripe-Signature": "t=1700000000,v1=fake-local-signature",
    }
    response = client.post("/billing/webhook", content=raw, headers=headers)
    assert response.status_code == 200
    assert provider.calls == [(raw, headers["Stripe-Signature"])]
    request = ContractRequest(
        method="post",
        url="http://127.0.0.1:18765/billing/webhook",
        body=raw,
        content_type="application/json",
        headers=headers,
    )
    contract.validate_request(request)
    assert_status_and_media(response, 200, "application/json")
    contract.validate_response(
        request, ContractResponse(response.status_code, response.content, dict(response.headers))
    )

    for signature in (None, "t=1,v1=invalid"):
        invalid_headers = {"Content-Type": "application/json"}
        if signature:
            invalid_headers["Stripe-Signature"] = signature
        invalid = client.post("/billing/webhook", content=raw, headers=invalid_headers)
        assert invalid.status_code == 400
        assert_status_and_media(invalid, 400, "application/json")
        invalid_request = ContractRequest(
            method="post",
            url="http://127.0.0.1:18765/billing/webhook",
            body=raw,
            content_type="application/json",
            headers=invalid_headers,
        )
        contract.validate_response(
            invalid_request,
            ContractResponse(invalid.status_code, invalid.content, dict(invalid.headers)),
        )


def assert_canonical_413(contract, request, response):
    assert response.json() == {"detail": "Webhook payload is too large."}
    assert_status_and_media(response, 413, "application/json")
    contract.validate_response(
        request,
        ContractResponse(response.status_code, response.content, dict(response.headers)),
    )


def test_webhook_body_limit_is_stream_counted(contract, local_api):
    client, _, accounts = local_api
    provider = RecordingWebhookProvider()
    app.dependency_overrides[deps.get_accounts] = lambda: replace(
        accounts,
        billing_provider=provider,
    )
    fixed = len(b'{"pad":""}')
    exact = b'{"pad":"' + b"a" * (MAX_WEBHOOK_BODY_BYTES - fixed) + b'"}'
    headers = {
        "Content-Type": "application/json",
        "Stripe-Signature": "t=1700000000,v1=fake-local-signature",
    }
    assert len(exact) == MAX_WEBHOOK_BODY_BYTES
    exact_response = client.post("/billing/webhook", content=exact, headers=headers)
    exact_request = ContractRequest(
        method="post",
        url="http://127.0.0.1:18765/billing/webhook",
        body=exact,
        content_type="application/json",
        headers=headers,
    )
    assert_status_and_media(exact_response, 200, "application/json")
    contract.validate_response(
        exact_request,
        ContractResponse(
            exact_response.status_code,
            exact_response.content,
            dict(exact_response.headers),
        ),
    )
    assert provider.calls == [(exact, headers["Stripe-Signature"])]

    over = b'{"pad":"' + b"a" * (MAX_WEBHOOK_BODY_BYTES - fixed + 1) + b'"}'
    oversized = client.post("/billing/webhook", content=over, headers=headers)
    assert_canonical_413(
        contract,
        ContractRequest(
            method="post",
            url="http://127.0.0.1:18765/billing/webhook",
            body=over,
            content_type="application/json",
            headers=headers,
        ),
        oversized,
    )

    declared_headers = {**headers, "Content-Length": str(MAX_WEBHOOK_BODY_BYTES + 1)}
    declared = client.post(
        "/billing/webhook",
        content=b"{}",
        headers=declared_headers,
    )
    assert_canonical_413(
        contract,
        ContractRequest(
            method="post",
            url="http://127.0.0.1:18765/billing/webhook",
            body=b"{}",
            content_type="application/json",
            headers=declared_headers,
        ),
        declared,
    )

    misleading_headers = {**headers, "Content-Length": "1"}
    misleading = client.post(
        "/billing/webhook",
        content=over,
        headers=misleading_headers,
    )
    assert_canonical_413(
        contract,
        ContractRequest(
            method="post",
            url="http://127.0.0.1:18765/billing/webhook",
            body=over,
            content_type="application/json",
            headers=misleading_headers,
        ),
        misleading,
    )


class ChunkedBody(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def test_webhook_rejects_oversized_chunked_body_without_content_length(contract, local_api):
    _, _, accounts = local_api
    provider = RecordingWebhookProvider()
    app.dependency_overrides[deps.get_accounts] = lambda: replace(
        accounts,
        billing_provider=provider,
    )
    chunks = [b'{"pad":"', b"a" * MAX_WEBHOOK_BODY_BYTES, b'"}']
    captured_headers = {}
    headers = {
        "Content-Type": "application/json",
        "Stripe-Signature": "t=1700000000,v1=fake-local-signature",
    }

    async def recording_app(scope, receive, send):
        captured_headers.update(
            {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope["headers"]
            }
        )
        await app(scope, receive, send)

    async def send():
        transport = httpx.ASGITransport(app=recording_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:18765",
        ) as client:
            return await client.post(
                "/billing/webhook",
                content=ChunkedBody(chunks),
                headers=headers,
            )

    response = asyncio.run(send())
    request = ContractRequest(
        method="post",
        url="http://127.0.0.1:18765/billing/webhook",
        body=b"".join(chunks),
        content_type="application/json",
        headers={**headers, "Transfer-Encoding": "chunked"},
    )
    assert_canonical_413(contract, request, response)
    assert "content-length" not in captured_headers
    assert captured_headers["transfer-encoding"] == "chunked"
    assert provider.calls == []
