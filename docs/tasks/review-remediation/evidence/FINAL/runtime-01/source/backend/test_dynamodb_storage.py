from __future__ import annotations

import uuid

from auth.dynamodb_email_auth import DynamoEmailAuthService
from core.ids import generate_uuid7
from repositories.dynamodb_page_preload_repository import DynamoPagePreloadRepository
from repositories.dynamodb_phrase_repository import DynamoPhraseRepository
from storage.dynamodb_store import DynamoDbStore


def test_dynamodb_auth_login_and_resolve_user(
    dynamodb_store: DynamoDbStore,
) -> None:
    auth = DynamoEmailAuthService(dynamodb_store)
    email = f"test-{uuid.uuid4()}@example.com"

    access_token, user = auth.login(email=email, display_name="Test User")
    assert access_token
    assert user.email == email

    resolved = auth.resolve_user(access_token)
    assert resolved is not None
    assert resolved.id == user.id

    auth.logout(access_token)
    assert auth.resolve_user(access_token) is None


def test_dynamodb_page_preload_repository(
    dynamodb_store: DynamoDbStore,
) -> None:
    repository = DynamoPagePreloadRepository(dynamodb_store)
    user_id = generate_uuid7()
    page_url = f"https://example.com/articles/{uuid.uuid4()}"
    record = {
        "id": generate_uuid7(),
        "page_url": page_url,
        "page_title": "Example",
        "summary": "Summary",
        "topics": [],
        "sentences": [],
        "vocabulary": [],
        "created_at": "2026-01-01T00:00:00+00:00",
    }

    saved = repository.save(user_id, record)
    assert saved["user_id"] == user_id

    by_url = repository.get_by_page_url(user_id, page_url)
    assert by_url is not None
    assert by_url["id"] == record["id"]

    by_id = repository.get_by_id(user_id, record["id"])
    assert by_id is not None
    assert by_id["page_url"] == page_url.rstrip("/")


def test_dynamodb_phrase_repository(dynamodb_store: DynamoDbStore) -> None:
    repository = DynamoPhraseRepository(dynamodb_store)
    user_id = generate_uuid7()
    record = {
        "id": generate_uuid7(),
        "text": "break the ice",
        "translation": "打ち解ける",
        "created_at": "2026-01-01T00:00:00+00:00",
    }

    created = repository.create(user_id, record)
    assert created["user_id"] == user_id

    phrases = repository.list_for_user(user_id)
    assert any(item["id"] == record["id"] for item in phrases)
