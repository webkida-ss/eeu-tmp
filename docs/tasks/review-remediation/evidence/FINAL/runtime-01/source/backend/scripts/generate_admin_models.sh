#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUTPUT="${1:-$ROOT/backend/generated/admin_models.py}"
VENV="${BACKEND_VENV:-backend/.venv}"
if [[ "$VENV" != /* ]]; then
  VENV="$ROOT/$VENV"
fi

mkdir -p "$(dirname "$OUTPUT")"
"$VENV/bin/python" "$ROOT/scripts/schema/schema_tasks.py" generate-admin --output "$OUTPUT"
