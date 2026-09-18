#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${DYNAMODB_LOCAL_CONTAINER_NAME:-english-dynamodb-local}"
PORT="${DYNAMODB_LOCAL_PORT:-18000}"

if docker ps --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  if ! docker port "${CONTAINER_NAME}" 8000/tcp | grep -qE "[:.]${PORT}$"; then
    echo "Recreating DynamoDB Local with port ${PORT}."
    docker rm --force "${CONTAINER_NAME}" > /dev/null
  else
    echo "DynamoDB Local is already running on port ${PORT}."
    exit 0
  fi
fi

if docker ps --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  echo "DynamoDB Local is already running on port ${PORT}."
  exit 0
fi

if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  if ! docker port "${CONTAINER_NAME}" 8000/tcp 2>/dev/null | grep -qE "[:.]${PORT}$"; then
    echo "Recreating stopped DynamoDB Local with port ${PORT}."
    docker rm --force "${CONTAINER_NAME}" > /dev/null
  else
    docker start "${CONTAINER_NAME}" > /dev/null
    echo "Started existing DynamoDB Local container on port ${PORT}."
    exit 0
  fi
fi

if docker ps -a --format '{{.Names}}' | grep -qx "${CONTAINER_NAME}"; then
  docker start "${CONTAINER_NAME}" > /dev/null
  echo "Started existing DynamoDB Local container on port ${PORT}."
  exit 0
fi

docker run \
  --detach \
  --name "${CONTAINER_NAME}" \
  --publish "${PORT}:8000" \
  amazon/dynamodb-local > /dev/null

echo "Started new DynamoDB Local container on port ${PORT}."
