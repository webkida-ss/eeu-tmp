#!/usr/bin/env bash
# Reproduce Terraform provider locks without modifying the working tree.

set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TERRAFORM_PROVIDER_MIRROR="${TERRAFORM_PROVIDER_MIRROR:-}"

if [[ -n "${TERRAFORM_PROVIDER_MIRROR}" && ! -d "${TERRAFORM_PROVIDER_MIRROR}" ]]; then
  echo "TERRAFORM_PROVIDER_MIRROR must be an existing directory: ${TERRAFORM_PROVIDER_MIRROR}" >&2
  exit 1
fi
if [[ -n "${TERRAFORM_PROVIDER_MIRROR}" ]]; then
  TERRAFORM_PROVIDER_MIRROR="$(cd "${TERRAFORM_PROVIDER_MIRROR}" && pwd -P)"
fi

TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/terraform-lock-check.XXXXXXXX")"

cleanup() {
  rm -rf "${TEMP_ROOT}"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

mkdir -p "${TEMP_ROOT}/infra"
cp -R \
  "${REPOSITORY_ROOT}/infra/envs" \
  "${REPOSITORY_ROOT}/infra/modules" \
  "${TEMP_ROOT}/infra/"
rm -rf \
  "${TEMP_ROOT}/infra/envs/dev/.terraform" \
  "${TEMP_ROOT}/infra/envs/prod/.terraform"

for environment in dev prod; do
  "${REPOSITORY_ROOT}/scripts/bootstrap.sh" --exec terraform \
    -chdir="${TEMP_ROOT}/infra/envs/${environment}" \
    init \
    -backend=false \
    -input=false \
    -lockfile=readonly
  PROVIDER_LOCK_ARGS=(providers lock)
  if [[ -n "${TERRAFORM_PROVIDER_MIRROR}" ]]; then
    PROVIDER_LOCK_ARGS+=("-fs-mirror=${TERRAFORM_PROVIDER_MIRROR}")
  fi
  PROVIDER_LOCK_ARGS+=(
    -platform=darwin_arm64
    -platform=darwin_amd64
    -platform=linux_amd64
    -platform=linux_arm64
  )
  "${REPOSITORY_ROOT}/scripts/bootstrap.sh" --exec terraform \
    -chdir="${TEMP_ROOT}/infra/envs/${environment}" \
    "${PROVIDER_LOCK_ARGS[@]}"
  cmp \
    "${REPOSITORY_ROOT}/infra/envs/${environment}/.terraform.lock.hcl" \
    "${TEMP_ROOT}/infra/envs/${environment}/.terraform.lock.hcl"
done
