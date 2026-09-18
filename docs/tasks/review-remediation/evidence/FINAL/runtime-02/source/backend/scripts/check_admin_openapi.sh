#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMP_DIR="$(mktemp -d "$ROOT/backend/generated/.admin-models-check.XXXXXX")"
trap 'rm -rf "$TEMP_DIR"' EXIT

"$ROOT/backend/scripts/generate_admin_models.sh" "$TEMP_DIR/admin_models.py"
diff -u \
  "$ROOT/backend/generated/admin_models.py" \
  "$TEMP_DIR/admin_models.py"
