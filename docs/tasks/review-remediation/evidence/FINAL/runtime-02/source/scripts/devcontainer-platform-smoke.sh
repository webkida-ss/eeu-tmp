#!/usr/bin/env bash
set -euo pipefail

readonly EXPECTED_ARCH="${1:?usage: devcontainer-platform-smoke.sh EXPECTED_ARCH}"
readonly ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

case "${EXPECTED_ARCH}" in
  amd64) expected_uname="x86_64" ;;
  arm64) expected_uname="aarch64" ;;
  *) printf 'unsupported expected architecture: %s\n' "${EXPECTED_ARCH}" >&2; exit 2 ;;
esac

[[ "$(id -u)" -ne 0 ]] || {
  printf 'platform smoke must run as a non-root user\n' >&2
  exit 1
}
[[ "$(uname -m)" == "${expected_uname}" ]] || {
  printf 'runtime architecture mismatch: expected %s, got %s\n' "${expected_uname}" "$(uname -m)" >&2
  exit 1
}

source /etc/os-release
[[ "${ID}" == "ubuntu" && "${VERSION_ID}" == "24.04" ]]
grep -Fq 'https://snapshot.ubuntu.com/ubuntu/20260719T000000Z/' \
  /etc/apt/sources.list.d/ubuntu.sources
grep -Fq 'Check-Valid-Until: no' /etc/apt/sources.list.d/ubuntu.sources

dpkg-query -W \
  build-essential \
  ca-certificates \
  curl \
  git \
  libasound2t64 \
  libgbm1 \
  libnss3 \
  python3 \
  unzip \
  xz-utils \
  zip >/dev/null

export BOOTSTRAP_TOOLS_DIR="${ROOT}/.platform-tools"
cd -- "${ROOT}"
./scripts/bootstrap.sh
./scripts/bootstrap.sh --verify

printf 'platform=%s user=%s python=%s node=%s terraform=%s task=%s\n' \
  "${EXPECTED_ARCH}" \
  "$(id -u)" \
  "$(./scripts/bootstrap.sh --exec python --version 2>&1)" \
  "$(./scripts/bootstrap.sh --exec node --version)" \
  "$(./scripts/bootstrap.sh --exec terraform version | awk 'NR == 1')" \
  "$(./scripts/bootstrap.sh --exec task --version)"
