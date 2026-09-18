#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${DYNAMODB_LOCAL_CONTAINER_NAME:-english-dynamodb-local}"

if ! docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  echo "DynamoDB Local container does not exist."
  exit 0
fi

docker rm --force "${CONTAINER_NAME}" > /dev/null
echo "Removed DynamoDB Local container: ${CONTAINER_NAME}"
