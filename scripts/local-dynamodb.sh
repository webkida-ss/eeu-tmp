#!/usr/bin/env bash

set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ "${DYNAMODB_LOCAL_PORT+x}" == "x" ]]; then
  local_port="${DYNAMODB_LOCAL_PORT}"
else
  local_port="18000"
fi

if ! [[ "${local_port}" =~ ^[1-9][0-9]{0,4}$ ]] || ((10#${local_port} > 65535)); then
  echo "DYNAMODB_LOCAL_PORT must be an integer from 1 through 65535." >&2
  exit 2
fi

hash_identity() {
  if command -v shasum >/dev/null 2>&1; then
    printf '%s\n%s\n' "${root_dir}" "${local_port}" | shasum -a 256 | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    printf '%s\n%s\n' "${root_dir}" "${local_port}" | sha256sum | awk '{print $1}'
  else
    echo "A SHA-256 tool (shasum or sha256sum) is required to identify this worktree safely." >&2
    exit 1
  fi
}

identity_hash="$(hash_identity)"
compose_project="untangle-ddb-${identity_hash:0:24}-p${local_port}"
runtime_dir="${root_dir}/.runtime/dynamodb-local"
lock_dir="${runtime_dir}/${identity_hash}.lock"
lock_token=""
lock_held=0
lock_mode=""
reclaimed_mode=""
test_pid=""
output_file=""
service_owned=0

compose() {
  env DYNAMODB_LOCAL_PORT="${local_port}" \
    docker compose \
      --env-file /dev/null \
      --project-name "${compose_project}" \
      --file "${root_dir}/compose.yaml" \
      "$@"
}

metadata_field() {
  local field="$1"
  local metadata_path="$2"
  awk -F= -v field="${field}" '$1 == field {sub(/^[^=]*=/, ""); print; exit}' "${metadata_path}"
}

write_lock_metadata() {
  local child_pid="${1:-}"
  local metadata_tmp="${lock_dir}/metadata.$$"
  printf 'pid=%s\nchild_pid=%s\nmode=%s\nroot=%s\nport=%s\nproject=%s\nstarted_epoch=%s\ntoken=%s\n' \
    "$$" "${child_pid}" "${lock_mode}" "${root_dir}" "${local_port}" \
    "${compose_project}" "$(date +%s)" "${lock_token}" >"${metadata_tmp}"
  mv "${metadata_tmp}" "${lock_dir}/metadata"
}

release_lock() {
  if [[ "${lock_held}" -ne 1 ]]; then
    return
  fi
  local current_token=""
  if [[ -f "${lock_dir}/metadata" ]]; then
    current_token="$(metadata_field token "${lock_dir}/metadata")"
  fi
  if [[ "${current_token}" == "${lock_token}" ]]; then
    rm -rf "${lock_dir}"
  else
    echo "Warning: lock ownership changed; refusing to remove '${lock_dir}'." >&2
  fi
  lock_held=0
}

acquire_lock() {
  local mode="$1"
  local owner_pid owner_child_pid owner_mode owner_root owner_port owner_ps
  local child_ps child_ps_status ps_status stale_dir

  mkdir -p "${runtime_dir}"
  while ! mkdir "${lock_dir}" 2>/dev/null; do
    if [[ ! -f "${lock_dir}/metadata" ]]; then
      echo "DynamoDB automation lock '${lock_dir}' has no complete metadata; refusing unsafe reclamation. If no invocation is creating it, inspect and remove it manually." >&2
      return 1
    fi
    owner_pid="$(metadata_field pid "${lock_dir}/metadata")"
    owner_child_pid="$(metadata_field child_pid "${lock_dir}/metadata")"
    owner_mode="$(metadata_field mode "${lock_dir}/metadata")"
    owner_root="$(metadata_field root "${lock_dir}/metadata")"
    owner_port="$(metadata_field port "${lock_dir}/metadata")"
    if ! [[ "${owner_pid}" =~ ^[1-9][0-9]*$ ]]; then
      echo "DynamoDB automation lock '${lock_dir}' has invalid owner metadata; refusing unsafe reclamation." >&2
      return 1
    fi
    set +e
    owner_ps="$(ps -p "${owner_pid}" -o pid= 2>/dev/null)"
    ps_status=$?
    set -e
    if kill -0 "${owner_pid}" 2>/dev/null || [[ "${ps_status}" -eq 0 && -n "${owner_ps}" ]]; then
      echo "DynamoDB automation is already active (PID ${owner_pid}, mode ${owner_mode}, port ${owner_port}, root ${owner_root}). Wait for it to finish or use a distinct DYNAMODB_LOCAL_PORT." >&2
      return 1
    fi
    if [[ "${ps_status}" -ne 1 ]]; then
      echo "Could not prove that lock owner PID ${owner_pid} is dead; refusing unsafe reclamation of '${lock_dir}'." >&2
      return 1
    fi
    if [[ -n "${owner_child_pid}" ]]; then
      if ! [[ "${owner_child_pid}" =~ ^[1-9][0-9]*$ ]]; then
        echo "DynamoDB automation lock '${lock_dir}' has invalid child metadata; refusing unsafe reclamation." >&2
        return 1
      fi
      set +e
      child_ps="$(ps -p "${owner_child_pid}" -o pid= 2>/dev/null)"
      child_ps_status=$?
      set -e
      if kill -0 "${owner_child_pid}" 2>/dev/null || [[ "${child_ps_status}" -eq 0 && -n "${child_ps}" ]]; then
        echo "DynamoDB automation owner PID ${owner_pid} is dead, but child PID ${owner_child_pid} is still active. Stop that child before retrying; resources were left untouched." >&2
        return 1
      fi
      if [[ "${child_ps_status}" -ne 1 ]]; then
        echo "Could not prove that lock child PID ${owner_child_pid} is dead; refusing unsafe reclamation of '${lock_dir}'." >&2
        return 1
      fi
    fi

    stale_dir="${lock_dir}.stale.$$"
    if mv "${lock_dir}" "${stale_dir}" 2>/dev/null; then
      reclaimed_mode="${owner_mode}"
      rm -rf "${stale_dir}"
    fi
  done

  lock_token="$$-$(date +%s)-${RANDOM}"
  lock_mode="${mode}"
  write_lock_metadata
  lock_held=1
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker is required for local DynamoDB integration tests. Install Docker Desktop (or another Docker Engine) and retry." >&2
    exit 1
  fi
  if ! compose version >/dev/null 2>&1; then
    echo "Docker Compose v2 is required. Install or enable the 'docker compose' plugin and retry." >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "Docker is installed but the daemon is unavailable. Start Docker Desktop (or your Docker Engine) and retry." >&2
    exit 1
  fi
}

up_unlocked() {
  if ! compose up --detach; then
    echo "Could not start DynamoDB Local on 127.0.0.1:${local_port}." >&2
    echo "Another checkout or process may own the port. Stop it, or retry with an unused port, for example: DYNAMODB_LOCAL_PORT=18001 task test:backend:integration:local" >&2
    return 1
  fi
}

run_manual() {
  local action="$1"
  require_docker
  acquire_lock "manual-${action}"
  trap release_lock EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  if [[ "${action}" == "up" ]]; then
    if ! up_unlocked; then
      compose down --remove-orphans >/dev/null 2>&1 || true
      return 1
    fi
  else
    compose down --remove-orphans
  fi
  trap - EXIT HUP INT TERM
  release_lock
}

lifecycle_cleanup() {
  local status="${1:-$?}"
  if [[ "${test_pid}" =~ ^[1-9][0-9]*$ ]]; then
    kill -TERM "${test_pid}" >/dev/null 2>&1 || true
    wait "${test_pid}" >/dev/null 2>&1 || true
    test_pid=""
  fi
  if [[ "${service_owned}" -eq 1 ]]; then
    if ! compose down --remove-orphans >/dev/null 2>&1; then
      echo "Warning: failed to tear down DynamoDB Compose project '${compose_project}'. Run 'task dynamodb:down' after Docker is available." >&2
    fi
    service_owned=0
  fi
  if [[ -n "${output_file}" ]]; then
    rm -f "${output_file}"
    output_file=""
  fi
  release_lock
  return "${status}"
}

run_integration() {
  require_docker
  acquire_lock "integration"
  output_file="$(mktemp)"

  on_signal() {
    exit "$1"
  }

  trap lifecycle_cleanup EXIT
  trap 'on_signal 129' HUP
  trap 'on_signal 130' INT
  trap 'on_signal 143' TERM

  if [[ "${reclaimed_mode}" == "integration" ]]; then
    compose down --remove-orphans
  elif [[ -n "$(compose ps --all --quiet)" ]]; then
    echo "This worktree/port already has DynamoDB Compose resources not owned by this integration invocation. Run 'task dynamodb:down' first." >&2
    return 1
  fi

  service_owned=1
  up_unlocked

  local runner="${DYNAMODB_INTEGRATION_TEST_RUNNER:-${root_dir}/backend/.venv/bin/python}"
  set +e
  DYNAMODB_INTEGRATION_ENDPOINT="http://127.0.0.1:${local_port}" \
    "${runner}" -m pytest -q -rs \
      "${root_dir}/backend/test_dynamodb_storage.py" \
      "${root_dir}/backend/test_preload_dynamodb_integration.py" \
      >"${output_file}" 2>&1 &
  test_pid=$!
  write_lock_metadata "${test_pid}"
  wait "${test_pid}"
  local test_status=$?
  test_pid=""
  set -e

  tee /dev/stderr <"${output_file}" >/dev/null
  local result=0
  if [[ "${test_status}" -ne 0 ]]; then
    result="${test_status}"
  elif grep -qi 'skipped' "${output_file}" || ! grep -Eq '(^|[^0-9])4 passed([^0-9]|$)' "${output_file}"; then
    echo "Expected exactly four non-skipped DynamoDB integration tests." >&2
    result=1
  fi

  trap - EXIT HUP INT TERM
  lifecycle_cleanup 0
  return "${result}"
}

case "${1:-}" in
  up)
    run_manual up
    ;;
  down)
    run_manual down
    ;;
  test)
    run_integration
    ;;
  config)
    require_docker
    compose config
    ;;
  identity)
    printf '%s\n' "${compose_project}"
    ;;
  *)
    echo "Usage: $0 {up|down|test|config|identity}" >&2
    exit 2
    ;;
esac
