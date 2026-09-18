#!/usr/bin/env bash
set -euo pipefail

TABLE_NAME="${DYNAMODB_TABLE_NAME:-english-local-learning-catalog}"
ENDPOINT_URL="${DYNAMODB_ENDPOINT:-http://localhost:18000}"
AWS_REGION="${AWS_REGION:-ap-northeast-1}"

export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-dummy}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-dummy}"
export AWS_REGION

tmp_file="$(mktemp)"
trap 'rm -f "${tmp_file}"' EXIT

aws dynamodb scan \
  --table-name "${TABLE_NAME}" \
  --endpoint-url "${ENDPOINT_URL}" \
  --output json > "${tmp_file}"

python3 - "${tmp_file}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as file:
    data = json.load(file)

items = data.get("Items", [])

print(f"items: {len(items)}")

for item in sorted(items, key=lambda value: value.get("sk", {}).get("S", "")):
    pk = item.get("pk", {}).get("S", "")
    sk = item.get("sk", {}).get("S", "")
    document_text = item.get("document", {}).get("S")

    print(f"\n{pk} {sk}")

    if document_text is None:
        print("  document: <missing>")
        continue

    document = json.loads(document_text)
    courses = document.get("courses", [])
    units = [unit for course in courses for unit in course.get("units", [])]
    vocabulary_entries = [
        entry
        for unit in units
        for entry in unit.get("vocabularyEntries", [])
    ]

    print(f"  id: {document.get('id')}")
    print(f"  title: {document.get('title')}")
    print(f"  courses: {len(courses)}")
    print(f"  units: {len(units)}")
    print(f"  vocabularyEntries: {len(vocabulary_entries)}")

    for course in courses:
        print(f"    - course: {course.get('id')} / {course.get('title')}")
PY
