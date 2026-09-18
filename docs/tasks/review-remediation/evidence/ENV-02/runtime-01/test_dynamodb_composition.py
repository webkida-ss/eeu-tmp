from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest import mock

import deps
from accounts import AccountsSettings
from auth.dynamodb_email_auth import DynamoEmailAuthService
from storage import dynamodb_store
from storage.dynamodb_keys import SK_SESSION, session_pk


class MemoryDynamoStore:
    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], dict[str, object]] = {}

    def get_document(self, partition_key: str, sort_key: str) -> dict[str, object] | None:
        document = self.documents.get((partition_key, sort_key))
        return dict(document) if document is not None else None

    def put_document(
        self,
        partition_key: str,
        sort_key: str,
        document: dict[str, object],
    ) -> dict[str, object]:
        self.documents[(partition_key, sort_key)] = dict(document)
        return document

    def delete(self, partition_key: str, sort_key: str) -> None:
        self.documents.pop((partition_key, sort_key), None)


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def test_dynamodb_factories_use_default_credentials_outside_local() -> None:
    synthetic_role_credentials = {
        "AWS_ACCESS_KEY_ID": "ASIAEXAMPLE",
        "AWS_SECRET_ACCESS_KEY": "synthetic-secret",
        "AWS_SESSION_TOKEN": "synthetic-session-token",
    }
    with (
        mock.patch.dict(os.environ, synthetic_role_credentials, clear=False),
        mock.patch.object(dynamodb_store, "DYNAMODB_ENDPOINT", None),
        mock.patch.object(dynamodb_store.boto3, "resource") as resource,
        mock.patch.object(dynamodb_store.boto3, "client") as client,
    ):
        dynamodb_store.create_dynamodb_resource()
        dynamodb_store.create_dynamodb_client()

    expected_kwargs = {"region_name": dynamodb_store.AWS_REGION}
    resource.assert_called_once_with("dynamodb", **expected_kwargs)
    client.assert_called_once_with("dynamodb", **expected_kwargs)


def test_dynamodb_factories_use_dummy_credentials_only_for_local() -> None:
    endpoint = "http://dynamodb-local.invalid:8000"
    with (
        mock.patch.object(dynamodb_store, "DYNAMODB_ENDPOINT", endpoint),
        mock.patch.object(dynamodb_store.boto3, "resource") as resource,
        mock.patch.object(dynamodb_store.boto3, "client") as client,
    ):
        dynamodb_store.create_dynamodb_resource()
        dynamodb_store.create_dynamodb_client()

    expected_kwargs = {
        "region_name": dynamodb_store.AWS_REGION,
        "endpoint_url": endpoint,
        "aws_access_key_id": "dummy",
        "aws_secret_access_key": "dummy",
    }
    resource.assert_called_once_with("dynamodb", **expected_kwargs)
    client.assert_called_once_with("dynamodb", **expected_kwargs)


def test_store_builds_resource_and_transaction_client_with_one_credential_policy() -> None:
    resource = mock.Mock()
    client = mock.Mock()
    resource.Table.return_value.name = "reading-assistant"
    with (
        mock.patch.object(
            dynamodb_store,
            "create_dynamodb_resource",
            return_value=resource,
        ) as resource_factory,
        mock.patch.object(
            dynamodb_store,
            "create_dynamodb_client",
            return_value=client,
        ) as client_factory,
    ):
        store = dynamodb_store.DynamoDbStore(table_name="reading-assistant")

    resource_factory.assert_called_once_with()
    client_factory.assert_called_once_with()
    assert store._client is client


def test_dynamo_auth_composition_uses_configured_ttl_and_rejects_expired_session() -> None:
    start = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)
    clock = MutableClock(start)
    store = MemoryDynamoStore()
    settings = AccountsSettings(session_ttl_days=1)

    with (
        mock.patch.object(deps, "STORAGE_BACKEND", "dynamodb"),
        mock.patch.object(deps, "ACCOUNTS_SETTINGS", settings),
    ):
        auth = deps._create_auth_service(store=store, clock=clock)

    assert isinstance(auth, DynamoEmailAuthService)
    access_token, user = auth.login(email="reader@example.test")
    session = store.get_document(session_pk(access_token), SK_SESSION)
    assert session is not None
    assert session["user_id"] == user.id
    assert session["expires_at"] == (start + timedelta(days=1)).isoformat()

    clock.now = start + timedelta(days=1) - timedelta(seconds=1)
    resolved = auth.resolve_user(access_token)
    assert resolved is not None
    assert resolved.id == user.id

    clock.now = start + timedelta(days=1)
    assert auth.resolve_user(access_token) is None
    assert store.get_document(session_pk(access_token), SK_SESSION) is None
