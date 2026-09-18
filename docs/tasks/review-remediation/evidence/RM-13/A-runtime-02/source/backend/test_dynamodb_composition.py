from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import deps
import pytest
from accounts import AccountsSettings
from accounts.models import User
from auth.dynamodb_email_auth import DynamoEmailAuthService
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError
from storage import dynamodb_store
from storage.dynamodb_keys import SK_PROFILE, SK_SESSION, SK_USER, email_pk, session_pk, user_pk

_DESERIALIZER = TypeDeserializer()


class MemoryDynamoStore:
    table_name = "auth-test"

    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], dict[str, object]] = {}
        self.transactions: list[list[dict[str, object]]] = []
        self.consistent_reads: list[tuple[str, str]] = []
        self.before_transact = None
        self.transaction_error: ClientError | None = None

    def get_document(
        self, partition_key: str, sort_key: str, *, consistent_read: bool = False
    ) -> dict[str, object] | None:
        if consistent_read:
            self.consistent_reads.append((partition_key, sort_key))
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

    def transact_write(self, transactions: list[dict[str, object]]) -> None:
        self.transactions.append(transactions)
        if self.transaction_error is not None:
            raise self.transaction_error
        if self.before_transact is not None:
            callback = self.before_transact
            self.before_transact = None
            callback()

        decoded = [self._decode_put(transaction) for transaction in transactions]
        for partition_key, sort_key, _document, condition in decoded:
            if condition != "attribute_not_exists(pk) AND attribute_not_exists(sk)":
                raise AssertionError(f"Unexpected condition: {condition}")
            if (partition_key, sort_key) in self.documents:
                raise _conditional_transaction_failure()
        for partition_key, sort_key, document, _condition in decoded:
            self.documents[(partition_key, sort_key)] = document

    @staticmethod
    def _decode_put(transaction: dict[str, object]) -> tuple[str, str, dict[str, object], str]:
        put = transaction["Put"]
        assert isinstance(put, dict)
        item = {field: _DESERIALIZER.deserialize(value) for field, value in put["Item"].items()}
        return (
            str(item["pk"]),
            str(item["sk"]),
            json.loads(str(item["document"])),
            str(put["ConditionExpression"]),
        )


def _conditional_transaction_failure() -> ClientError:
    return ClientError(
        {
            "Error": {"Code": "TransactionCanceledException", "Message": "conditional"},
            "CancellationReasons": [
                {"Code": "ConditionalCheckFailed"},
                {"Code": "None"},
            ],
        },
        "TransactWriteItems",
    )


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


def test_dynamo_auth_first_login_uses_one_conditional_identity_transaction() -> None:
    store = MemoryDynamoStore()
    auth = DynamoEmailAuthService(store)

    access_token, user = auth.login(email=" Reader@Example.Test ", display_name="Reader")

    assert uuid.UUID(user.id).version == 7
    assert len(store.transactions) == 1
    transaction = store.transactions[0]
    assert len(transaction) == 2
    decoded = [MemoryDynamoStore._decode_put(item) for item in transaction]
    assert {key[:2] for key in decoded} == {
        (email_pk("reader@example.test"), SK_USER),
        (user_pk(user.id), SK_PROFILE),
    }
    assert all(
        condition == "attribute_not_exists(pk) AND attribute_not_exists(sk)"
        for *_, condition in decoded
    )
    assert store.documents[(email_pk("reader@example.test"), SK_USER)] == {"user_id": user.id}
    assert store.documents[(user_pk(user.id), SK_PROFILE)]["email"] == "reader@example.test"
    assert store.get_document(session_pk(access_token), SK_SESSION)["user_id"] == user.id


def test_dynamo_auth_concurrent_first_logins_recover_the_same_winner() -> None:
    store = MemoryDynamoStore()
    first = DynamoEmailAuthService(store)
    second = DynamoEmailAuthService(store)
    second_result: list[tuple[str, User]] = []

    def complete_second_login() -> None:
        second_result.append(second.login(email="reader@example.test", display_name="Second"))

    store.before_transact = complete_second_login
    first_token, first_user = first.login(email="reader@example.test", display_name="First")
    second_token, second_user = second_result[0]

    assert first_user.id == second_user.id
    assert first_user.display_name == "Second"
    assert first_token != second_token
    assert len(store.transactions) == 2
    assert store.get_document(session_pk(first_token), SK_SESSION)["user_id"] == first_user.id
    assert store.get_document(session_pk(second_token), SK_SESSION)["user_id"] == first_user.id
    assert (email_pk("reader@example.test"), SK_USER) in store.consistent_reads
    assert (user_pk(first_user.id), SK_PROFILE) in store.consistent_reads
    profile_keys = [key for key in store.documents if key[1] == SK_PROFILE]
    assert profile_keys == [(user_pk(first_user.id), SK_PROFILE)]


def test_dynamo_auth_uses_a_validated_existing_identity_without_a_transaction() -> None:
    store = MemoryDynamoStore()
    store.put_document(email_pk("reader@example.test"), SK_USER, {"user_id": "winner"})
    store.put_document(
        user_pk("winner"),
        SK_PROFILE,
        {"id": "winner", "email": "reader@example.test", "display_name": "Original"},
    )

    access_token, user = DynamoEmailAuthService(store).login(
        email="reader@example.test", display_name="Updated"
    )

    assert user.id == "winner"
    assert user.display_name == "Updated"
    assert store.transactions == []
    assert store.documents[(user_pk("winner"), SK_PROFILE)]["display_name"] == "Updated"
    assert store.get_document(session_pk(access_token), SK_SESSION)["user_id"] == "winner"


@pytest.mark.parametrize(
    "email_lookup, profile",
    [
        ({"user_id": 42}, None),
        ({"user_id": "winner"}, None),
        (
            {"user_id": "winner"},
            {"id": "other-user", "email": "reader@example.test", "display_name": "Other"},
        ),
        (
            {"user_id": "winner"},
            {"id": "winner", "email": "other@example.test", "display_name": "Other"},
        ),
    ],
)
def test_dynamo_auth_rejects_malformed_or_dangling_existing_identity(
    email_lookup: dict[str, object], profile: dict[str, object] | None
) -> None:
    store = MemoryDynamoStore()
    store.put_document(email_pk("reader@example.test"), SK_USER, email_lookup)
    if profile is not None:
        store.put_document(user_pk("winner"), SK_PROFILE, profile)
    original_documents = dict(store.documents)

    with pytest.raises(ValueError, match="identity"):
        DynamoEmailAuthService(store).login(email="reader@example.test")

    assert not [key for key in store.documents if key[1] == SK_SESSION]
    assert store.documents == original_documents
    assert (email_pk("reader@example.test"), SK_USER) in store.consistent_reads


def test_dynamo_auth_uuid_collision_keeps_the_email_claim_absent() -> None:
    store = MemoryDynamoStore()
    store.put_document(
        user_pk("collision-id"),
        SK_PROFILE,
        {"id": "collision-id", "email": "other@example.test", "display_name": "Other"},
    )

    with (
        mock.patch("auth.dynamodb_email_auth.generate_uuid7", return_value="collision-id"),
        pytest.raises(ValueError, match="identity"),
    ):
        DynamoEmailAuthService(store).login(email="reader@example.test")

    assert (email_pk("reader@example.test"), SK_USER) not in store.documents
    assert store.documents[(user_pk("collision-id"), SK_PROFILE)]["email"] == "other@example.test"
    assert not [key for key in store.documents if key[1] == SK_SESSION]


def test_dynamo_auth_rejects_a_corrupt_winner_after_conditional_conflict() -> None:
    store = MemoryDynamoStore()

    def create_corrupt_winner() -> None:
        store.put_document(email_pk("reader@example.test"), SK_USER, {"user_id": "winner"})
        store.put_document(
            user_pk("winner"),
            SK_PROFILE,
            {"id": "other-user", "email": "reader@example.test", "display_name": "Other"},
        )

    store.before_transact = create_corrupt_winner
    with pytest.raises(ValueError, match="identity"):
        DynamoEmailAuthService(store).login(email="reader@example.test")

    assert not [key for key in store.documents if key[1] == SK_SESSION]
    assert len(store.transactions) == 1
    assert (email_pk("reader@example.test"), SK_USER) in store.consistent_reads


@pytest.mark.parametrize(
    "error_response",
    [
        {"Error": {"Code": "ValidationException", "Message": "invalid transaction"}},
        {
            "Error": {"Code": "TransactionCanceledException", "Message": "malformed"},
            "CancellationReasons": [
                {"Code": "ConditionalCheckFailed"},
                {},
            ],
        },
    ],
)
def test_dynamo_auth_nonconditional_transaction_failure_does_not_become_contention(
    error_response: dict[str, object],
) -> None:
    store = MemoryDynamoStore()
    store.transaction_error = ClientError(error_response, "TransactWriteItems")

    with pytest.raises(ClientError):
        DynamoEmailAuthService(store).login(email="reader@example.test")

    assert store.documents == {}
