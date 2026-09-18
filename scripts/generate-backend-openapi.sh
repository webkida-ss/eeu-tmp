#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GENERATOR_VERSION="${OPENAPI_GENERATOR_VERSION:-7.19.0}"
GENERATOR_JAR="${ROOT_DIR}/.cache/openapi-generator/openapi-generator-cli-${GENERATOR_VERSION}.jar"
GENERATOR_URL="https://repo1.maven.org/maven2/org/openapitools/openapi-generator-cli/${GENERATOR_VERSION}/openapi-generator-cli-${GENERATOR_VERSION}.jar"
OUTPUT_DIR="${ROOT_DIR}/backend/generated/openapi"

mkdir -p "$(dirname "${GENERATOR_JAR}")"

if [[ ! -f "${GENERATOR_JAR}" ]]; then
  curl -L -o "${GENERATOR_JAR}" "${GENERATOR_URL}"
fi

rm -rf "${OUTPUT_DIR}"

java -jar "${GENERATOR_JAR}" generate \
  -i "${ROOT_DIR}/contracts/openapi/openapi.yaml" \
  -g rust-axum \
  -o "${OUTPUT_DIR}" \
  --additional-properties packageName=english_backend_openapi,packageVersion=0.1.0 \
  --generate-alias-as-model
