from __future__ import annotations

import json
import sys
from pathlib import Path

import deps
import pytest
from accounts import User
from accounts.billing import MockBillingProvider
from accounts.storage import JsonSubscriptionRepository
from accounts.testing import build_test_accounts
from core.plans import PLAN_CATALOG
from fastapi.testclient import TestClient
from main import app
from openapi_contract_support import (
    ContractRequest,
    ContractResponse,
    assert_status_and_media,
    encode_body,
    openapi_from_bundle,
)
from repositories.page_preload_repository import JsonPagePreloadRepository
from repositories.phrase_repository import JsonPhraseRepository
from repositories.usage_repository import JsonUsageRepository

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "schema"))
from schema_tasks import redocly_bundle  # noqa: E402

CASE_DOCUMENT = json.loads(
    (ROOT / "backend" / "generated" / "openapi-contract-cases.json").read_text(encoding="utf-8")
)
CASES = CASE_DOCUMENT["cases"]
GENERIC_CASES = [case for case in CASES if case["mode"] == "generic"]
MANUAL_CASES = [case for case in CASES if case["mode"] == "manual"]


class ContractAuthService:
    def __init__(self, user: User) -> None:
        self.user = user

    def login(self, *, email: str, display_name: str | None = None) -> tuple[str, User]:
        return "fake-local-session", self.user

    def resolve_user(self, access_token: str) -> User | None:
        return self.user if access_token else None

    def logout(self, access_token: str) -> None:
        return None


@pytest.fixture(scope="session")
def contract():
    return openapi_from_bundle(redocly_bundle())


@pytest.fixture
def client(tmp_path):
    user = User(
        id="018f47a2-7b3c-7abc-8def-0123456789ab",
        email="learner@example.test",
        display_name="Learner",
    )
    subscriptions = JsonSubscriptionRepository(tmp_path / "subscriptions.json")
    accounts = build_test_accounts(
        plans=PLAN_CATALOG,
        auth_service=ContractAuthService(user),
        subscription_repository=subscriptions,
        billing_provider=MockBillingProvider(PLAN_CATALOG),
    )
    app.dependency_overrides[deps.get_accounts] = lambda: accounts
    app.dependency_overrides[deps.get_current_user] = lambda: user
    app.dependency_overrides[deps.get_page_preload_repository] = lambda: JsonPagePreloadRepository(
        tmp_path / "preloads.json"
    )
    app.dependency_overrides[deps.get_phrase_repository] = lambda: JsonPhraseRepository(
        tmp_path / "phrases.json"
    )
    app.dependency_overrides[deps.get_subscription_repository] = lambda: subscriptions
    app.dependency_overrides[deps.get_usage_repository] = lambda: JsonUsageRepository(
        tmp_path / "usage.json"
    )
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def contract_request(case):
    headers = {}
    if case["auth"] == "localBearer":
        headers["Authorization"] = "Bearer fake-local-session"
    if case["requestMediaType"]:
        headers["Content-Type"] = case["requestMediaType"]
    return ContractRequest(
        method=case["method"].lower(),
        url=f"http://127.0.0.1:18765{case['path']}",
        body=encode_body(case["requestBody"], case["requestMediaType"]),
        content_type=case["requestMediaType"] or "",
        headers=headers,
        path_parameters={
            key: value
            for key, value in case["parameters"].items()
            if "{" + key + "}" in case["path"]
        },
    )


@pytest.mark.parametrize(
    "case",
    GENERIC_CASES,
    ids=lambda case: f"{case['operationId']}[{case['caseId']}]",
)
def test_generated_contract_case(contract, client, case):
    request = contract_request(case)
    contract.validate_request(request)
    expected = ContractResponse(
        status_code=case["expectedStatus"],
        data=encode_body(case["responseExample"], case["expectedMediaType"]),
        headers={"content-type": case["expectedMediaType"]},
    )
    contract.validate_response(request, expected)

    if not case["invoke"]:
        return

    request_kwargs = {"headers": dict(request.headers or {})}
    if case["requestBody"] is not None:
        request_kwargs["content"] = request.body
    actual = client.request(case["method"], case["path"], **request_kwargs)
    assert_status_and_media(actual, case["expectedStatus"], case["expectedMediaType"])
    contract.validate_response(
        request,
        ContractResponse(actual.status_code, actual.content, dict(actual.headers)),
    )


def test_all_generic_singular_response_examples_are_generated():
    bundle = redocly_bundle()
    expected = set()
    for _path, path_item in bundle["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}:
                continue
            if operation["x-contract-test"]["mode"] != "generic":
                continue
            for status, response in operation["responses"].items():
                for media_type, media in response.get("content", {}).items():
                    if "example" in media:
                        expected.add((operation["operationId"], int(status), media_type))

    generated = {
        (case["operationId"], case["expectedStatus"], case["expectedMediaType"])
        for case in GENERIC_CASES
        if case["caseKind"] == "documentedError"
    }
    assert generated == expected
    assert generated


def test_manual_cases_are_owned_and_never_generically_invoked():
    assert {case["operationId"] for case in MANUAL_CASES} == {
        "createAuthSession",
        "createBillingCheckout",
        "createChatReply",
        "createPagePreload",
        "analyzeText",
        "openBillingPortal",
        "processBillingWebhook",
        "getAdminSession",
    }
    for case in MANUAL_CASES:
        assert case["invoke"] is False
        assert case["owner"]
        assert case["reason"]
        assert (ROOT / case["test"].split("::", 1)[0]).is_file()
