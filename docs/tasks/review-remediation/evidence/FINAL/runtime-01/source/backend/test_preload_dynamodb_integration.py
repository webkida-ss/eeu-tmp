from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from accounts.storage import JsonEmailAuthService, JsonSubscriptionRepository
from accounts.testing import build_test_accounts
from core.plans import PLAN_CATALOG
from deps import (
    get_accounts,
    get_page_preload_repository,
    get_preload_content_store,
    get_preload_job_runner,
    get_subscription_repository,
    get_usage_repository,
)
from fastapi.testclient import TestClient
from main import app
from repositories.dynamodb_page_preload_repository import (
    DynamoPagePreloadRepository,
)
from repositories.usage_repository import JsonUsageRepository
from storage.dynamodb_keys import user_pk
from storage.dynamodb_store import DynamoDbStore
from storage.preload_content_store import FilesystemPreloadContentStore


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def enqueue(
        self,
        user_id: str,
        page_url: str,
        preload_id: str,
        learner_profile_fingerprint: str,
        usage_context: dict[str, Any] | None = None,
    ) -> None:
        self.calls.append(
            (
                user_id,
                page_url,
                preload_id,
                learner_profile_fingerprint,
                usage_context,
            )
        )


@dataclass
class PreloadIntegrationContext:
    client: TestClient
    preloads: DynamoPagePreloadRepository
    runner: RecordingRunner


@pytest.fixture
def preload_integration_context(
    tmp_path: Path,
    dynamodb_store: DynamoDbStore,
) -> Iterator[PreloadIntegrationContext]:
    auth_service = JsonEmailAuthService(
        tmp_path / "users.json",
        tmp_path / "sessions.json",
    )
    usage = JsonUsageRepository(tmp_path / "usage.json")
    subscriptions = JsonSubscriptionRepository(tmp_path / "subscriptions.json")
    preloads = DynamoPagePreloadRepository(dynamodb_store)
    content = FilesystemPreloadContentStore(tmp_path / "preload-content")
    runner = RecordingRunner()

    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    accounts = build_test_accounts(
        plans=PLAN_CATALOG,
        auth_service=auth_service,
        subscription_repository=subscriptions,
    )
    app.dependency_overrides[get_accounts] = lambda: accounts
    app.dependency_overrides[get_page_preload_repository] = lambda: preloads
    app.dependency_overrides[get_usage_repository] = lambda: usage
    app.dependency_overrides[get_subscription_repository] = lambda: subscriptions
    app.dependency_overrides[get_preload_content_store] = lambda: content
    app.dependency_overrides[get_preload_job_runner] = lambda: runner
    client = TestClient(app, raise_server_exceptions=False)

    try:
        yield PreloadIntegrationContext(
            client=client,
            preloads=preloads,
            runner=runner,
        )
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def test_preload_submission_persists_to_dynamodb_and_returns_202(
    preload_integration_context: PreloadIntegrationContext,
    dynamodb_store: DynamoDbStore,
) -> None:
    context = preload_integration_context
    login = context.client.post(
        "/auth/login",
        json={"credential": "mock:reader@example.com"},
    )
    assert login.status_code == 200, login.text
    user_id = login.json()["user"]["id"]
    headers = {
        "Authorization": f"Bearer {login.json()['access_token']}",
    }
    page_url = "https://example.com/integration"

    response = context.client.post(
        "/pages/preload",
        json={
            "page_url": page_url,
            "page_title": "Integration",
            "html": (
                "<article>"
                "<p>The quick brown fox jumps over the lazy dog every morning.</p>"
                "<p>She sells fresh seashells by the seashore in summer.</p>"
                "<p>Programming languages evolve as developers demand more power.</p>"
                "</article>"
            ),
        },
        headers=headers,
    )

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "processing"

    stored = context.preloads.get_by_page_url(user_id, page_url)
    assert stored is not None
    assert stored["status"] == "processing"
    assert len(context.runner.calls) == 1

    user_records = dynamodb_store.query_by_pk(user_pk(user_id))
    immutable_records = [record for record in user_records if record.get("id") == stored["id"]]
    url_indexes = [
        record
        for record in user_records
        if record.get("preload_id") == stored["id"] and "id" not in record
    ]
    assert len(user_records) == 2
    assert len(immutable_records) == 1
    assert len(url_indexes) == 1
