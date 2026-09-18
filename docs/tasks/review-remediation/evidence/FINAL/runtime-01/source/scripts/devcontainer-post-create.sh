#!/usr/bin/env bash
set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
export BACKEND_VENV="backend/.devcontainer-venv"
export BOOTSTRAP_TOOLS_DIR="${ROOT}/.devcontainer-tools"
export REPOSITORY_TOOLS_DIR="${ROOT}/.devcontainer-tools/repository"

fail() {
  printf 'devcontainer setup: error: %s\n' "$*" >&2
  exit 1
}

[[ "$(id -u)" -ne 0 ]] || fail "post-create setup must run as a non-root user."
[[ ! -S /var/run/docker.sock ]] || fail "Docker socket must not be mounted in the dev container."
[[ -z "${SSH_AUTH_SOCK:-}" ]] || fail "SSH agent forwarding is disabled by default."

cd -- "${ROOT}"
manifest="$(mktemp /tmp/untangle-workspace-manifest.XXXXXXXX.json)"
trap 'rm -f -- "${manifest}"' EXIT HUP INT TERM
/usr/bin/python3 ./scripts/workspace-manifest.py capture --root "${ROOT}" --manifest "${manifest}"

./scripts/bootstrap.sh
./scripts/bootstrap.sh --exec task setup
./scripts/bootstrap.sh --exec task setup:browser

/usr/bin/python3 ./scripts/workspace-manifest.py verify --root "${ROOT}" --manifest "${manifest}" ||
  fail "bootstrap/setup changed protected workspace content."

printf 'Dev container setup complete. Run: task check\n'
