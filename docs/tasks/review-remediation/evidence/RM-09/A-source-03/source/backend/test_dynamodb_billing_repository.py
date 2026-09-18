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
            if kind == "Put" and "attribute_not_exists(pk)" in condition and current:
                owner = item.pop("_expected_owner")
                legacy_document = item.pop("_expected_legacy_document", None)
                if (
                    current.get("owner_user_id") != owner
                    and current.get("document") != legacy_document
                ):
                    raise _conditional_failure()
            if kind == "Delete":
                owner = item.pop("_expected_owner")
                legacy_document = item.pop("_expected_legacy_document", None)
                if not current or (
                    current.get("owner_user_id") != owner
                    and current.get("document") != legacy_document
                ):
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
        condition = operation.get("ConditionExpression", "")
        for alias in operation.get("ExpressionAttributeNames", {}):
            if alias not in condition:
                raise AssertionError(f"Unused Dynamo expression name: {alias}")
        if ":revision" in values:
            item["_expected_revision"] = _DESERIALIZER.deserialize(values[":revision"])
        if ":owner" in values:
            item["_expected_owner"] = _DESERIALIZER.deserialize(values[":owner"])
        if ":legacy_document" in values:
            item["_expected_legacy_document"] = _DESERIALIZER.deserialize(
                values[":legacy_document"]
            )
        return kind, item, condition


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
            "pending_checkout": {
                "operation_id": "op-1",
                "user_id": "user-1",
                "requested_plan": "pro",
                "price_id": "price_pro",
                "success_url": "https://app.example/success",
                "cancel_url": "https://app.example/cancel",
                "stripe_customer_id": None,
                "customer_choice": "email",
                "email": "user-1@example.test",
                "idempotency_key": "key-1",
                "operation_metadata": {"operation_id": "op-1"},
                "state": "reserved",
            },
            "plan": "basic",
            "status": "canceled",
        },
    )
    attempted_pending = {
        **initial["pending_checkout"],
        "state": "attempted",
        "creation_attempted_at": 1,
    }

    assert (
        second.compare_and_swap(
            "user-1",
            {
                "plan": "pro",
                "status": "active",
                "pending_checkout": attempted_pending,
            },
            expected_revision=initial["revision"],
        )
        is not None
    )
    first.upsert("user-1", initial)
    assert (
        first.compare_and_swap(
            "user-1",
            {"plan": "max", "status": "active"},
            expected_revision=initial["revision"],
        )
        is None
    )
    record = first.get("user-1")
    assert record["pending_checkout"]["state"] == "attempted"
    assert record["pending_checkout"]["creation_attempted_at"] == 1


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


def test_dynamo_upgrades_only_the_exact_legacy_customer_index_owner() -> None:
    store = FakeConditionalDynamoStore()
    repository = DynamoSubscriptionRepository(store)
    repository.upsert("user-1", {"stripe_customer_id": "cus_legacy"})
    legacy_key = next(key for key in store.attributes if key[0].endswith("cus_legacy"))
    store.attributes[legacy_key].pop("owner_user_id")

    repository.upsert("user-1", {"stripe_customer_id": "cus_legacy"})
    assert store.attributes[legacy_key]["owner_user_id"] == "user-1"

    store.attributes[legacy_key].pop("owner_user_id")
    repository.upsert("user-1", {"stripe_customer_id": "cus_upgraded"})

    assert repository.find_user_by_customer("cus_legacy") is None
    assert repository.find_user_by_customer("cus_upgraded") == "user-1"
