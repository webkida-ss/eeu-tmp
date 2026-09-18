#!/usr/bin/env bash
# Start the local backend stack: DynamoDB Local, table bootstrap, uvicorn.
#
# Run this in your own terminal so the process stays alive across chat turns.
# Requires Docker and a prepared backend/.venv (see README).
#
# Usage: backend/dev.sh

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${BACKEND_DIR}"

if [[ ! -x "${BACKEND_DIR}/.venv/bin/uvicorn" ]]; then
  echo "Missing backend/.venv. Run:" >&2
  echo "  cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required for local DynamoDB. Install Docker or set STORAGE_BACKEND=json." >&2
  exit 1
fi

echo "Starting DynamoDB Local (port 18000)..."
docker compose up -d --remove-orphans dynamodb

echo "Ensuring DynamoDB table exists..."
bash "${BACKEND_DIR}/scripts/create-reading-assistant-table.sh"

echo "Starting backend on http://127.0.0.1:18765 ..."
exec "${BACKEND_DIR}/.venv/bin/uvicorn" main:app --reload --port 18765
