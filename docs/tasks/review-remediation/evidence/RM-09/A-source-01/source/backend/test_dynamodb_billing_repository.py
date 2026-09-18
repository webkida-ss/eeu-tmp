from __future__ import annotations

import json

import pytest
from boto3.dynamodb.types import TypeDeserializer
from repositories.dynamodb_billing_repositories import DynamoSubscriptionRepository

_DESERIALIZER = TypeDeserializer()


class FakeConditionalDynamoStore:
    """Transaction-aware fake for subscription CAS and customer ownership."""

    table_name = "billing-test"

    def __init__(self) -> None:
        self.documents: dict[tuple[str, str], dict[str, object]] = {}
        self.attributes: dict[tuple[str, str], dict[str, object]] = {}

    def get_document(
        self, partition_key: str, sort_key: str, *, consistent_read: bool = False
    ) -> dict[str, object] | None:
        document = self.documents.get((partition_key, sort_key))
        return dict(document) if document is not None else None

    def transact_write(self, transactions: list[dict[str, object]]) -> None:
        decoded = [self._decode(transaction) for transaction in transactions]
        for kind, item, condition in decoded:
            current = self.attributes.get((item["pk"], item["sk"]))
            if (
                kind == "Put"
                and condition == "attribute_not_exists(#revision)"
                and current
                and "revision" in current
            ):
                raise _conditional_failure()
            if kind == "Put" and condition == "#revision = :revision":
                expected = item.pop("_expected_revision")
                if not current or current.get("revision") != expected:
                    raise _conditional_failure()
            if kind == "Put" and condition == "attribute_not_exists(pk) OR #owner = :owner":
                owner = item.pop("_expected_owner")
                if current and current.get("owner_user_id") != owner:
                    raise _conditional_failure()
            if kind == "Delete":
                owner = item.pop("_expected_owner")
                if not current or current.get("owner_user_id") != owner:
                    raise _conditional_failure()
        for kind, item, _condition in decoded:
            key = (item["pk"], item["sk"])
            if kind == "Delete":
                self.documents.pop(key, None)
                self.attributes.pop(key, None)
            else:
                self.documents[key] = json.loads(item["document"])
                self.attributes[key] = dict(item)

    @staticmethod
    def _decode(transaction: dict[str, object]) -> tuple[str, dict[str, object], str]:
        kind, operation = next(iter(transaction.items()))
        operation = operation  # type: ignore[assignment]
        if kind == "Delete":
            item = {
                name: _DESERIALIZER.deserialize(value) for name, value in operation["Key"].items()
            }
        else:
            item = {
                name: _DESERIALIZER.deserialize(value) for name, value in operation["Item"].items()
            }
        values = operation.get("ExpressionAttributeValues", {})
        if ":revision" in values:
            item["_expected_revision"] = _DESERIALIZER.deserialize(values[":revision"])
        if ":owner" in values:
            item["_expected_owner"] = _DESERIALIZER.deserialize(values[":owner"])
        return kind, item, operation.get("ConditionExpression", "")


def _conditional_failure():
    from botocore.exceptions import ClientError

    return ClientError(
        {"Error": {"Code": "TransactionCanceledException", "Message": "conditional"}},
        "TransactWriteItems",
    )


def test_dynamo_subscription_cas_preserves_pending_operation_and_rejects_stale_write() -> None:
    store = FakeConditionalDynamoStore()
    first = DynamoSubscriptionRepository(store)
    second = DynamoSubscriptionRepository(store)
    initial = first.upsert(
        "user-1",
        {
            "pending_checkout": {"operation_id": "op-1"},
            "plan": "basic",
            "status": "canceled",
        },
    )

    assert (
        second.compare_and_swap(
            "user-1",
            {"plan": "pro", "status": "active"},
            expected_revision=initial["revision"],
        )
        is not None
    )
    assert (
        first.compare_and_swap(
            "user-1",
            {"plan": "max", "status": "active"},
            expected_revision=initial["revision"],
        )
        is None
    )
    record = first.get("user-1")
    assert record["plan"] == "pro"
    assert record["pending_checkout"]["operation_id"] == "op-1"


def test_dynamo_customer_index_rejects_collision_and_removes_old_owned_index() -> None:
    store = FakeConditionalDynamoStore()
    first = DynamoSubscriptionRepository(store)
    second = DynamoSubscriptionRepository(store)
    first.upsert("user-1", {"stripe_customer_id": "cus_first"})

    with pytest.raises(ValueError, match="already owned"):
        second.upsert("user-2", {"stripe_customer_id": "cus_first"})

    first.upsert("user-1", {"stripe_customer_id": "cus_second"})
    assert second.find_user_by_customer("cus_first") is None
    assert second.find_user_by_customer("cus_second") == "user-1"
