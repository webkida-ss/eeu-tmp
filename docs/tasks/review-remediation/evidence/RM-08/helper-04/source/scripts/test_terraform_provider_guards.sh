#!/usr/bin/env bash
# Run provider-guard Terraform tests from an isolated module copy without cloud access.

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
MODULE_SOURCE="${REPOSITORY_ROOT}/infra/modules/reading-assistant-api"
DEV_LOCKFILE="${REPOSITORY_ROOT}/infra/envs/dev/.terraform.lock.hcl"
TERRAFORM_PROVIDER_MIRROR="${TERRAFORM_PROVIDER_MIRROR:-}"

fail() {
  printf 'provider-guard tests: %s\n' "$*" >&2
  exit 1
}

[[ -n "${TERRAFORM_PROVIDER_MIRROR}" ]] || fail "TERRAFORM_PROVIDER_MIRROR is required for offline provider schemas."
[[ -d "${TERRAFORM_PROVIDER_MIRROR}" ]] || fail "TERRAFORM_PROVIDER_MIRROR must be an existing directory."
TERRAFORM_PROVIDER_MIRROR="$(cd -- "${TERRAFORM_PROVIDER_MIRROR}" && pwd -P)"

AWS_PROVIDER_MIRROR_ROOT="${TERRAFORM_PROVIDER_MIRROR}/registry.terraform.io/hashicorp/aws"
[[ -d "${AWS_PROVIDER_MIRROR_ROOT}" ]] || fail "TERRAFORM_PROVIDER_MIRROR is missing the cached hashicorp/aws provider."
if ! find "${AWS_PROVIDER_MIRROR_ROOT}" \
  -type f \
  -size +0c \
  \( -name 'terraform-provider-aws_*' -o -name 'terraform-provider-aws_v*' \) \
  -print -quit | grep -q .; then
  fail "TERRAFORM_PROVIDER_MIRROR is missing the cached hashicorp/aws provider package."
fi

TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/terraform-provider-guards.XXXXXXXX")"

cleanup() {
  rm -rf -- "${TEMP_ROOT}"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

hcl_string() {
  local input="$1"
  local character next_character escaped=""
  local index

  for ((index = 0; index < ${#input}; index += 1)); do
    character="${input:index:1}"
    next_character="${input:index+1:1}"
    case "${character}" in
      \\) escaped+='\\' ;;
      '"') escaped+='\"' ;;
      $'\n') escaped+='\n' ;;
      $'\r') escaped+='\r' ;;
      $'\t') escaped+='\t' ;;
      '$')
        if [[ "${next_character}" == "{" ]]; then
          escaped+='$$'
        else
          escaped+="${character}"
        fi
        ;;
      '%')
        if [[ "${next_character}" == "{" ]]; then
          escaped+='%%'
        else
          escaped+="${character}"
        fi
        ;;
      *)
        [[ "${character}" =~ [[:cntrl:]] ]] &&
          fail "TERRAFORM_PROVIDER_MIRROR contains an unsupported control character."
        escaped+="${character}"
        ;;
    esac
  done

  printf '"%s"' "${escaped}"
}

PRIVATE_TF_CLI_CONFIG_FILE="${TEMP_ROOT}/terraformrc"
printf '%s\n' \
  'disable_checkpoint = true' \
  '' \
  'provider_installation {' \
  '  filesystem_mirror {' \
  "    path    = $(hcl_string "${TERRAFORM_PROVIDER_MIRROR}")" \
  '    include = ["registry.terraform.io/hashicorp/aws"]' \
  '  }' \
  '}' > "${PRIVATE_TF_CLI_CONFIG_FILE}"

# Ignore caller configuration so a network-capable installation method cannot be inherited.
export TF_CLI_CONFIG_FILE="${PRIVATE_TF_CLI_CONFIG_FILE}"

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
