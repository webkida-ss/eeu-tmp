#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:18080}"

request_ok() {
  local path="$1"
  curl --fail --silent --show-error "${BASE_URL}${path}" > /dev/null
  echo "OK ${path}"
}

request_status() {
  local path="$1"
  local expected_status="$2"
  local actual_status

  actual_status="$(curl --silent --output /dev/null --write-out '%{http_code}' "${BASE_URL}${path}")"

  if [[ "${actual_status}" != "${expected_status}" ]]; then
    echo "Expected ${path} to return ${expected_status}, got ${actual_status}" >&2
    exit 1
  fi

  echo "OK ${path} -> ${actual_status}"
}

request_ok "/healthz"
request_ok "/learning-paths"
request_ok "/learning-paths/toeic"
request_ok "/learning-paths/toeic/courses/starter"
request_status "/learning-paths/missing" "404"
