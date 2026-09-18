#!/usr/bin/env bash
# Run provider-guard Terraform tests from an isolated module copy without cloud access.

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
MODULE_SOURCE="${REPOSITORY_ROOT}/infra/modules/reading-assistant-api"
DEV_LOCKFILE="${REPOSITORY_ROOT}/infra/envs/dev/.terraform.lock.hcl"
TERRAFORM_PROVIDER_MIRROR="${TERRAFORM_PROVIDER_MIRROR:-}"
TF_CLI_CONFIG_FILE="${TF_CLI_CONFIG_FILE:-}"

fail() {
  printf 'provider-guard tests: %s\n' "$*" >&2
  exit 1
}

[[ -n "${TERRAFORM_PROVIDER_MIRROR}" ]] || fail "TERRAFORM_PROVIDER_MIRROR is required for offline provider schemas."
[[ -d "${TERRAFORM_PROVIDER_MIRROR}" ]] || fail "TERRAFORM_PROVIDER_MIRROR must be an existing directory."
[[ -n "${TF_CLI_CONFIG_FILE}" ]] || fail "TF_CLI_CONFIG_FILE is required to disable registry access."
[[ -f "${TF_CLI_CONFIG_FILE}" ]] || fail "TF_CLI_CONFIG_FILE must be an existing file."
grep -Eq 'filesystem_mirror' "${TF_CLI_CONFIG_FILE}" || fail "TF_CLI_CONFIG_FILE must configure a filesystem mirror."
if grep -Eq '^[[:space:]]*direct[[:space:]]*\{' "${TF_CLI_CONFIG_FILE}"; then
  fail "TF_CLI_CONFIG_FILE must not permit a direct registry fallback."
fi

TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/terraform-provider-guards.XXXXXXXX")"

cleanup() {
  rm -rf -- "${TEMP_ROOT}"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

STAGED_MODULE="${TEMP_ROOT}/module"
mkdir -p "${STAGED_MODULE}"
cp \
  "${MODULE_SOURCE}/main.tf" \
  "${MODULE_SOURCE}/outputs.tf" \
  "${MODULE_SOURCE}/variables.tf" \
  "${MODULE_SOURCE}/versions.tf" \
  "${STAGED_MODULE}/"
cp -R "${MODULE_SOURCE}/tests" "${STAGED_MODULE}/tests"
cp "${DEV_LOCKFILE}" "${STAGED_MODULE}/.terraform.lock.hcl"

"${REPOSITORY_ROOT}/scripts/bootstrap.sh" --exec terraform \
  -chdir="${STAGED_MODULE}" \
  init \
  -backend=false \
  -input=false \
  -lockfile=readonly
"${REPOSITORY_ROOT}/scripts/bootstrap.sh" --exec terraform \
  -chdir="${STAGED_MODULE}" \
  test \
  -test-directory=tests
