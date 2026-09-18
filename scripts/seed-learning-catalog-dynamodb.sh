#!/usr/bin/env bash
set -euo pipefail

TABLE_NAME="${DYNAMODB_TABLE_NAME:-english-local-learning-catalog}"
ENDPOINT_URL="${DYNAMODB_ENDPOINT:-http://localhost:18000}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"
CATALOG_DATA_PATH="${CATALOG_DATA_PATH:-frontend/src/features/learning/data/learningPaths.json}"

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-dummy}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-dummy}"
export AWS_REGION

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

python3 - "${CATALOG_DATA_PATH}" "${tmp_dir}" <<'PY'
import json
import pathlib
import sys

source = pathlib.Path(sys.argv[1])
output_dir = pathlib.Path(sys.argv[2])

paths = json.loads(source.read_text())

for learning_path in paths:
    item = {
        "pk": {"S": "CATALOG"},
        "sk": {"S": f"PATH#{learning_path['id']}"},
        "document": {
            "S": json.dumps(
                learning_path,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        },
    }
    (output_dir / f"{learning_path['id']}.json").write_text(
        json.dumps(item, ensure_ascii=False),
    )
PY

for item_file in "${tmp_dir}"/*.json; do
  aws dynamodb put-item \
    --table-name "${TABLE_NAME}" \
    --item "file://${item_file}" \
    --endpoint-url "${ENDPOINT_URL}" > /dev/null

  echo "Seeded $(basename "${item_file}" .json)"
done
