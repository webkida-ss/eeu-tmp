#!/usr/bin/env bash
set -euo pipefail

TABLE_NAME="${READING_ASSISTANT_DYNAMODB_TABLE_NAME:-english-local-reading-assistant}"
ENDPOINT_URL="${DYNAMODB_ENDPOINT:-http://localhost:18000}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-dummy}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-dummy}"
export AWS_REGION

if aws dynamodb describe-table \
  --table-name "${TABLE_NAME}" \
  --endpoint-url "${ENDPOINT_URL}" > /dev/null 2>&1; then
  echo "DynamoDB table already exists: ${TABLE_NAME}"
  exit 0
fi

aws dynamodb create-table \
  --table-name "${TABLE_NAME}" \
  --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S \
  --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --endpoint-url "${ENDPOINT_URL}" > /dev/null

aws dynamodb wait table-exists \
  --table-name "${TABLE_NAME}" \
  --endpoint-url "${ENDPOINT_URL}"

echo "Created DynamoDB table: ${TABLE_NAME}"
