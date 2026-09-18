from __future__ import annotations

import json
from typing import Any

import boto3
from boto3.dynamodb.types import TypeSerializer
from boto3.resources.base import ServiceResource
from botocore.exceptions import ClientError
from config import (
    AWS_REGION,
    DYNAMODB_ENDPOINT,
    READING_ASSISTANT_DYNAMODB_TABLE_NAME,
)

DOCUMENT_ATTRIBUTE = "document"
_SERIALIZER = TypeSerializer()


def _dynamodb_client_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "region_name": AWS_REGION,
    }
    if DYNAMODB_ENDPOINT:
        kwargs["endpoint_url"] = DYNAMODB_ENDPOINT
        # DynamoDB Local accepts any credentials; ignore real AWS profiles here.
        kwargs["aws_access_key_id"] = "dummy"
        kwargs["aws_secret_access_key"] = "dummy"
    return kwargs


def create_dynamodb_resource() -> ServiceResource:
    return boto3.resource("dynamodb", **_dynamodb_client_kwargs())


def create_dynamodb_client():
    return boto3.client("dynamodb", **_dynamodb_client_kwargs())


class DynamoDbStore:
    def __init__(
        self,
        *,
        table_name: str = READING_ASSISTANT_DYNAMODB_TABLE_NAME,
        resource: ServiceResource | None = None,
        client: Any | None = None,
    ) -> None:
        self._resource = resource or create_dynamodb_resource()
        self._table = self._resource.Table(table_name)
        if client is not None:
            self._client = client
        elif resource is not None:
            self._client = resource.meta.client
        else:
            self._client = create_dynamodb_client()

    @property
    def table_name(self) -> str:
        return self._table.name

    def get_item(self, pk: str, sk: str, *, consistent_read: bool = False) -> dict[str, Any] | None:
        response = self._table.get_item(
            Key={"pk": pk, "sk": sk},
            ConsistentRead=consistent_read,
        )
        return response.get("Item")

    def get_document(
        self, pk: str, sk: str, *, consistent_read: bool = False
    ) -> dict[str, Any] | None:
        item = self.get_item(pk, sk, consistent_read=consistent_read)
        if not item:
            return None
        return self._parse_document(item)

    def put_document(
        self,
        pk: str,
        sk: str,
        document: dict[str, Any],
        *,
        extra_attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item: dict[str, Any] = {
            "pk": pk,
            "sk": sk,
            DOCUMENT_ATTRIBUTE: json.dumps(document, ensure_ascii=False, separators=(",", ":")),
        }
        if extra_attributes:
            item.update(extra_attributes)
        self._table.put_item(Item=item)
        return document

    def put_document_if_absent(
        self,
        pk: str,
        sk: str,
        document: dict[str, Any],
        *,
        extra_attributes: dict[str, Any] | None = None,
    ) -> bool:
        item: dict[str, Any] = {
            "pk": pk,
            "sk": sk,
            DOCUMENT_ATTRIBUTE: json.dumps(document, ensure_ascii=False, separators=(",", ":")),
            **(extra_attributes or {}),
        }
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def put_documents_atomically(
        self,
        entries: list[tuple[str, str, dict[str, Any], dict[str, Any] | None]],
    ) -> None:
        transaction = []
        for pk, sk, document, extra_attributes in entries:
            item = {
                "pk": pk,
                "sk": sk,
                DOCUMENT_ATTRIBUTE: json.dumps(document, ensure_ascii=False, separators=(",", ":")),
                **(extra_attributes or {}),
            }
            transaction.append(
                {
                    "Put": {
                        "TableName": self.table_name,
                        "Item": {key: _SERIALIZER.serialize(value) for key, value in item.items()},
                    }
                }
            )
        self.transact_write(transaction)

    def conditional_put_document(
        self,
        pk: str,
        sk: str,
        document: dict[str, Any],
        *,
        extra_attributes: dict[str, Any],
        expected_attributes: dict[str, Any],
    ) -> bool:
        item: dict[str, Any] = {
            "pk": pk,
            "sk": sk,
            DOCUMENT_ATTRIBUTE: json.dumps(document, ensure_ascii=False, separators=(",", ":")),
            **extra_attributes,
        }
        names = {f"#field{i}": field for i, field in enumerate(expected_attributes)}
        values = {f":value{i}": value for i, value in enumerate(expected_attributes.values())}
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression=" AND ".join(
                    f"{name} = :value{i}" for i, name in enumerate(names)
                ),
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def delete(self, pk: str, sk: str) -> None:
        self._table.delete_item(Key={"pk": pk, "sk": sk})

    def add_to_counters(self, pk: str, sk: str, amounts: dict[str, int]) -> dict[str, int]:
        """Atomically increments top-level numeric attributes (creating the
        item as needed) and returns the new values. Used for usage counters,
        which must not lose increments under concurrent Lambda instances."""
        fields = list(amounts)
        response = self._table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="ADD " + ", ".join(f"#f{i} :v{i}" for i in range(len(fields))),
            ExpressionAttributeNames={f"#f{i}": field for i, field in enumerate(fields)},
            ExpressionAttributeValues={
                f":v{i}": int(amounts[field]) for i, field in enumerate(fields)
            },
            ReturnValues="ALL_NEW",
        )
        attributes = response.get("Attributes") or {}
        return {field: int(attributes.get(field) or 0) for field in fields}

    def get_counters(self, pk: str, sk: str, fields: list[str]) -> dict[str, int]:
        response = self._table.get_item(Key={"pk": pk, "sk": sk})
        item = response.get("Item") or {}
        return {field: int(item.get(field) or 0) for field in fields}

    def transact_write(self, items: list[dict[str, Any]]) -> None:
        """Commit pre-built low-level DynamoDB transaction items."""

        # Use a standalone low-level client: resource.meta.client rejects
        # TransactWriteItems against DynamoDB Local with ValidationException.
        self._client.transact_write_items(TransactItems=items)

    def query_by_pk(self, pk: str, *, sk_prefix: str | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "pk = :pk",
            "ExpressionAttributeValues": {":pk": pk},
        }
        if sk_prefix:
            kwargs["KeyConditionExpression"] = "pk = :pk AND begins_with(sk, :sk_prefix)"
            kwargs["ExpressionAttributeValues"][":sk_prefix"] = sk_prefix

        items: list[dict[str, Any]] = []
        response = self._table.query(**kwargs)
        items.extend(self._parse_items(response.get("Items", [])))

        while "LastEvaluatedKey" in response:
            response = self._table.query(**kwargs, ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(self._parse_items(response.get("Items", [])))

        return items

    def table_exists(self) -> bool:
        try:
            self._resource.meta.client.describe_table(TableName=self.table_name)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                return False
            raise

    @staticmethod
    def _parse_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        parsed: list[dict[str, Any]] = []
        for item in items:
            document = DynamoDbStore._parse_document(item)
            if document is not None:
                parsed.append(document)
        return parsed

    @staticmethod
    def _parse_document(item: dict[str, Any]) -> dict[str, Any] | None:
        raw_document = item.get(DOCUMENT_ATTRIBUTE)
        if not isinstance(raw_document, str):
            return None
        data = json.loads(raw_document)
        if not isinstance(data, dict):
            return None
        return data
