#!/usr/bin/env bash
set -euo pipefail

TABLE_NAME="${AI_MODEL_CATALOG_DYNAMODB_TABLE_NAME:-${DYNAMODB_TABLE_NAME:-english-local-learning-catalog}}"
ENDPOINT_URL="${DYNAMODB_ENDPOINT:-http://localhost:18000}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"
EXAMPLE_SENTENCE_PROVIDER="${AI_MODEL_CATALOG_EXAMPLE_SENTENCE_PROVIDER:-dev}"
EXAMPLE_SENTENCE_PROVIDER_MODEL_ID="${AI_MODEL_CATALOG_EXAMPLE_SENTENCE_PROVIDER_MODEL_ID:-dev-example-sentence-fast}"

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-dummy}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-dummy}"
export AWS_REGION

tmp_file="$(mktemp)"
trap 'rm -f "${tmp_file}"' EXIT

python3 - "${tmp_file}" "${EXAMPLE_SENTENCE_PROVIDER}" "${EXAMPLE_SENTENCE_PROVIDER_MODEL_ID}" <<'PY'
import json
import pathlib
import sys

output = pathlib.Path(sys.argv[1])
provider = sys.argv[2]
provider_model_id = sys.argv[3]

profile = {
    "key": "example_sentence_fast",
    "provider": provider,
    "providerModelId": provider_model_id,
}
item = {
    "pk": {"S": "AI_MODEL_CATALOG"},
    "sk": {"S": "MODEL#example_sentence_fast"},
    "document": {
        "S": json.dumps(profile, ensure_ascii=False, separators=(",", ":")),
    },
}

output.write_text(json.dumps(item, ensure_ascii=False))
PY

aws dynamodb put-item \
  --table-name "${TABLE_NAME}" \
  --item "file://${tmp_file}" \
  --endpoint-url "${ENDPOINT_URL}" > /dev/null

echo "Seeded AI model catalog: example_sentence_fast -> ${EXAMPLE_SENTENCE_PROVIDER}/${EXAMPLE_SENTENCE_PROVIDER_MODEL_ID}"
