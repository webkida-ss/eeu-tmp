from __future__ import annotations

import os
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from botocore.config import Config
from storage.dynamodb_store import DynamoDbStore

PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if PROJECT_ROOT not in sys.path:
    # `test:backend:unit` runs pytest from backend/, while policy tests import
    # root-level scripts as a namespace package.
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture(scope="module")
def dynamodb_store() -> Iterator[DynamoDbStore]:
    endpoint_url = os.getenv("DYNAMODB_INTEGRATION_ENDPOINT")
    if not endpoint_url:
        pytest.skip("DYNAMODB_INTEGRATION_ENDPOINT is not configured.")

    connection_options = {
        "endpoint_url": endpoint_url,
        "region_name": "ap-northeast-1",
        "aws_access_key_id": "dummy",
        "aws_secret_access_key": "dummy",
        "config": Config(
            connect_timeout=1,
            read_timeout=1,
            retries={"max_attempts": 0},
        ),
    }
    client = boto3.client("dynamodb", **connection_options)
    resource = boto3.resource("dynamodb", **connection_options)

    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client.list_tables()
            break
        except Exception as exc:  # noqa: BLE001 - readiness retries all service errors
            last_error = exc
            time.sleep(0.25)
    else:
        pytest.fail(
            f"Configured DynamoDB service at {endpoint_url} was unavailable "
            f"after 30 seconds: {last_error!r}"
        )

    table_name = f"english-test-reading-assistant-{uuid.uuid4()}"
    client.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    try:
        yield DynamoDbStore(
            table_name=table_name,
            resource=resource,
            client=client,
        )
    finally:
        client.delete_table(TableName=table_name)
