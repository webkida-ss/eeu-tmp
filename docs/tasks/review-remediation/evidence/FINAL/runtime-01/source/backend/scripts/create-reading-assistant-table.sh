#!/usr/bin/env bash
# Create the local DynamoDB table used by the reading-assistant backend.
#
# Idempotent: exits 0 when the table already exists. Waits up to 30 seconds
# for DynamoDB Local to accept connections.
#
# Usage: scripts/create-reading-assistant-table.sh

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "${BACKEND_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${BACKEND_DIR}/.env"
  set +a
fi

exec "${BACKEND_DIR}/.venv/bin/python" - <<'PY'
from __future__ import annotations

import os
import sys
import time

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

endpoint_url = os.getenv("DYNAMODB_ENDPOINT", "http://localhost:18000").strip()
table_name = os.getenv(
    "READING_ASSISTANT_DYNAMODB_TABLE_NAME",
    "english-local-reading-assistant",
).strip()
region_name = os.getenv("AWS_REGION", "ap-northeast-1").strip()

client = boto3.client(
    "dynamodb",
    endpoint_url=endpoint_url,
    region_name=region_name,
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "dummy"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "dummy"),
    config=Config(
        connect_timeout=1,
        read_timeout=1,
        retries={"max_attempts": 0},
    ),
)

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
    print(
        f"DynamoDB at {endpoint_url} was unavailable after 30 seconds: {last_error!r}",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    client.describe_table(TableName=table_name)
    print(f"DynamoDB table already exists: {table_name}")
    sys.exit(0)
except ClientError as exc:
    if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
        raise

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

client.get_waiter("table_exists").wait(TableName=table_name)

try:
    client.update_time_to_live(
        TableName=table_name,
        TimeToLiveSpecification={
            "Enabled": True,
            "AttributeName": "expires_at_epoch",
        },
    )
except ClientError as exc:
    code = exc.response.get("Error", {}).get("Code", "")
    if code not in {"ValidationException", "ResourceInUseException"}:
        raise

print(f"Created DynamoDB table: {table_name}")
PY
