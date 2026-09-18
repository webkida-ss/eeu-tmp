#!/usr/bin/env bash
# Build the AWS Lambda deployment package for the Untangle backend.
#
# Produces dist/reading-assistant-lambda.zip containing the app code plus
# dependencies from requirements-lambda.txt, resolved for the Lambda
# runtime (arm64, CPython 3.12, Amazon Linux 2023 compatible wheels). Terraform
# consumes the zip via var.lambda_zip_path; run this before terraform apply.
#
# Usage: scripts/build_lambda.sh
#   PYTHON_BIN=python3.12 scripts/build_lambda.sh   # override the interpreter

set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIP_RUNNER="${BACKEND_DIR}/../scripts/with-isolated-pypi.sh"
BUILD_DIR="${BACKEND_DIR}/build/lambda"
DIST_DIR="${BACKEND_DIR}/dist"
ZIP_PATH="${DIST_DIR}/reading-assistant-lambda.zip"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LAMBDA_WHEELHOUSE="${LAMBDA_WHEELHOUSE:-}"

# Top-level modules and packages that make up the application. Tests,
# local JSON data, the venv, and scripts are deliberately excluded.
APP_FILES=(
  main.py
  config.py
  deps.py
  schemas.py
  secret_resolver.py
  lambda_handler.py
  worker_handler.py
)
APP_PACKAGES=(
  accounts
  admin
  auth
  core
  generated
  jobs
  middleware
  repositories
  services
  storage
)

if [[ -n "${LAMBDA_WHEELHOUSE}" && ! -d "${LAMBDA_WHEELHOUSE}" ]]; then
  echo "LAMBDA_WHEELHOUSE must be an existing directory: ${LAMBDA_WHEELHOUSE}" >&2
  exit 1
fi
if [[ -n "${LAMBDA_WHEELHOUSE}" ]]; then
  LAMBDA_WHEELHOUSE="$(cd "${LAMBDA_WHEELHOUSE}" && pwd -P)"
fi

echo "Building Lambda package in ${BUILD_DIR}"
rm -rf "${BUILD_DIR}" "${ZIP_PATH}"
mkdir -p "${BUILD_DIR}" "${DIST_DIR}"

# Resolve dependencies for the Lambda runtime, not the build host.
# --only-binary=:all: fails fast if a dependency lacks an aarch64 wheel
# instead of silently packaging a host-platform build.
PIP_SOURCE_ARGS=(--index-url https://pypi.org/simple)
if [[ -n "${LAMBDA_WHEELHOUSE}" ]]; then
  PIP_SOURCE_ARGS=(--no-index --find-links "${LAMBDA_WHEELHOUSE}")
fi

"${PIP_RUNNER}" "${PYTHON_BIN}" -m pip install \
  "${PIP_SOURCE_ARGS[@]}" \
  --require-hashes \
  --requirement "${BACKEND_DIR}/requirements-lambda.txt" \
  --target "${BUILD_DIR}" \
  --platform manylinux_2_28_aarch64 \
  --platform manylinux2014_aarch64 \
  --implementation cp \
  --python-version 3.12 \
  --only-binary=:all: \
  --upgrade \
  --quiet

for file in "${APP_FILES[@]}"; do
  cp "${BACKEND_DIR}/${file}" "${BUILD_DIR}/"
done

for package in "${APP_PACKAGES[@]}"; do
  rsync -a \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    "${BACKEND_DIR}/${package}" "${BUILD_DIR}/"
done

# Keep the artifact lean and deterministic.
find "${BUILD_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "${BUILD_DIR}" -type f -name "*.pyc" -delete

(cd "${BUILD_DIR}" && zip -qr "${ZIP_PATH}" .)

echo "Built ${ZIP_PATH} ($(du -h "${ZIP_PATH}" | cut -f1))"
