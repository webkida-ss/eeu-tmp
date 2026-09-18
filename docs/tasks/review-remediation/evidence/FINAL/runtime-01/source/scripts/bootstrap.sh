#!/usr/bin/env bash
set -euo pipefail

declare -a INHERITED_MISE_VARIABLES=()
while IFS= read -r variable_name; do
  INHERITED_MISE_VARIABLES+=("${variable_name}")
  unset "${variable_name}"
done < <(compgen -e -- "MISE_" || true)

readonly MISE_VERSION="2026.7.7"
readonly PYTHON_VERSION="3.12.7"
readonly NODE_VERSION="22.23.1"
readonly TERRAFORM_VERSION="1.15.5"
readonly TASK_VERSION="3.40.0"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
REPOSITORY_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly REPOSITORY_ROOT
readonly TOOLS_ROOT="${BOOTSTRAP_TOOLS_DIR:-${REPOSITORY_ROOT}/.tools}"
readonly MISE_ROOT="${TOOLS_ROOT}/mise"
readonly MISE_BIN_DIR="${MISE_ROOT}/bin"
readonly MISE_BIN="${MISE_BIN_DIR}/mise"

export MISE_DATA_DIR="${MISE_ROOT}/data"
readonly MISE_SHIMS_DIR="${MISE_DATA_DIR}/shims"
export MISE_CACHE_DIR="${MISE_ROOT}/cache"
export MISE_STATE_DIR="${MISE_ROOT}/state"
export MISE_CONFIG_DIR="${MISE_ROOT}/config"
export MISE_GLOBAL_CONFIG_FILE="/dev/null"
export MISE_AUTO_INSTALL=0
export MISE_PYTHON_COMPILE=0
# Python 3.12.7 predates attestations for mise's precompiled python-build-standalone
# artifact. Mise still verifies the checksum published with that release.
export MISE_PYTHON_GITHUB_ATTESTATIONS=false
export MISE_YES=1

MODE="install"
OS_NAME=""
ARCH_NAME=""
MISE_CHECKSUM=""
DOWNLOAD_TEMP_DIR=""
declare -a EXEC_COMMAND=()

usage() {
  cat <<'EOF'
Usage: scripts/bootstrap.sh [--dry-run | --verify | --env]
       scripts/bootstrap.sh --exec COMMAND [ARG...]

  --dry-run  Validate the host and print the planned operations without changes.
  --verify   Verify that mise and all pinned tools are already installed.
  --env      Print shell commands that add the repository tools to PATH.
  --exec     Execute a command with the repository-managed toolchain.
EOF
}

fail() {
  printf 'bootstrap: error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 ||
    fail "Required command '$1' was not found. Install $1 and retry."
}

detect_platform() {
  local kernel machine macos_major
  kernel="$(uname -s)"
  machine="$(uname -m)"

  case "${kernel}" in
    Darwin)
      require_command sw_vers
      macos_major="$(sw_vers -productVersion | cut -d. -f1)"
      [[ "${macos_major}" =~ ^[0-9]+$ ]] ||
        fail "Could not determine the macOS major version."
      ((macos_major >= 14)) ||
        fail "macOS 14 or newer is required; found $(sw_vers -productVersion)."
      OS_NAME="macos"
      ;;
    Linux)
      [[ -r /etc/os-release ]] ||
        fail "Only Ubuntu 24.04 is supported on Linux, but /etc/os-release is unavailable."
      # /etc/os-release is an operating-system-owned data file.
      # shellcheck disable=SC1091
      . /etc/os-release
      [[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] ||
        fail "Ubuntu 24.04 is required; found ${PRETTY_NAME:-unknown Linux distribution}."
      OS_NAME="linux"
      ;;
    *)
      fail "Unsupported operating system '${kernel}'. Supported systems are macOS 14+ and Ubuntu 24.04."
      ;;
  esac

  case "${machine}" in
    arm64 | aarch64)
      ARCH_NAME="arm64"
      ;;
    x86_64 | amd64)
      ARCH_NAME="x64"
      ;;
    *)
      fail "Unsupported architecture '${machine}'. Supported architectures are arm64 and x86_64."
      ;;
  esac

  case "${OS_NAME}-${ARCH_NAME}" in
    linux-arm64)
      MISE_CHECKSUM="1b4ef061d25f0ceb508f11169482f3074e55c1698a1494f666386b2fcfb46b9b"
      ;;
    linux-x64)
      MISE_CHECKSUM="429f71e7e989908bf975aafac9066329c16e2d8fc7cd8e74fdf21dd6300ffe7c"
      ;;
    macos-arm64)
      MISE_CHECKSUM="5b890cccc75fc43a494b83ace21dbd2ee26120ff19ba1994cdcd054b3a15abbd"
      ;;
    macos-x64)
      MISE_CHECKSUM="7b860e6495eea9a264a16dae575ac20d5618ea2fe97905756c661eb02035c5d9"
      ;;
    *)
      fail "mise ${MISE_VERSION} is unavailable for ${OS_NAME}-${ARCH_NAME}."
      ;;
  esac
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    fail "A SHA-256 utility is required (sha256sum on Ubuntu or shasum on macOS)."
  fi
}

validate_managed_path() {
  local path relative current component
  path="$1"
  [[ "${path}" == "${REPOSITORY_ROOT}/"* ]] ||
    fail "Managed path must remain inside the repository: ${path}"

  relative="${path#"${REPOSITORY_ROOT}/"}"
  current="${REPOSITORY_ROOT}"
  while [[ -n "${relative}" ]]; do
    if [[ "${relative}" == */* ]]; then
      component="${relative%%/*}"
      relative="${relative#*/}"
    else
      component="${relative}"
      relative=""
    fi
    [[ -n "${component}" && "${component}" != "." && "${component}" != ".." ]] ||
      fail "Managed path contains an unsafe component: ${path}"
    current="${current}/${component}"
    [[ ! -L "${current}" ]] ||
      fail "Managed path component is a symlink: ${current}"
  done
}

validate_all_managed_paths() {
  local managed_path
  for managed_path in \
    "${TOOLS_ROOT}" \
    "${MISE_ROOT}" \
    "${MISE_BIN_DIR}" \
    "${MISE_BIN}" \
    "${MISE_SHIMS_DIR}" \
    "${MISE_DATA_DIR}" \
    "${MISE_CACHE_DIR}" \
    "${MISE_STATE_DIR}" \
    "${MISE_CONFIG_DIR}"; do
    validate_managed_path "${managed_path}"
  done
}

mise_checksum_matches() {
  [[ -f "${MISE_BIN}" && ! -L "${MISE_BIN}" ]] || return 1
  [[ "$(sha256_file "${MISE_BIN}")" == "${MISE_CHECKSUM}" ]]
}

require_verified_mise() {
  validate_all_managed_paths
  [[ -e "${MISE_BIN}" ]] ||
    fail "mise is not installed at ${MISE_BIN}. Run ./scripts/bootstrap.sh first."
  [[ -f "${MISE_BIN}" && ! -L "${MISE_BIN}" ]] ||
    fail "Cached mise path must be a regular, non-symlink file: ${MISE_BIN}"
  mise_checksum_matches ||
    fail "Cached mise failed the official SHA-256 check. Run ./scripts/bootstrap.sh to reinstall it safely."
  [[ -x "${MISE_BIN}" ]] ||
    fail "Verified mise binary is not executable: ${MISE_BIN}"
}

run_mise() {
  require_verified_mise
  "${MISE_BIN}" "$@"
}

cleanup_download() {
  if [[ -n "${DOWNLOAD_TEMP_DIR}" && -d "${DOWNLOAD_TEMP_DIR}" ]]; then
    rm -rf -- "${DOWNLOAD_TEMP_DIR}"
  fi
  DOWNLOAD_TEMP_DIR=""
}

install_mise() {
  local asset_name download_url download_path actual_checksum

  validate_all_managed_paths
  if mise_checksum_matches; then
    chmod 0755 "${MISE_BIN}"
    printf 'mise %s is already installed and checksum-verified.\n' "${MISE_VERSION}"
    return
  fi

  if [[ -e "${MISE_BIN}" || -L "${MISE_BIN}" ]]; then
    [[ -f "${MISE_BIN}" && ! -L "${MISE_BIN}" ]] ||
      fail "Refusing to replace non-regular cached mise path: ${MISE_BIN}"
    printf 'Cached mise checksum is invalid; preparing a verified replacement.\n' >&2
  fi

  asset_name="mise-v${MISE_VERSION}-${OS_NAME}-${ARCH_NAME}"
  download_url="https://github.com/jdx/mise/releases/download/v${MISE_VERSION}/${asset_name}"
  mkdir -p "${MISE_BIN_DIR}"
  validate_all_managed_paths
  DOWNLOAD_TEMP_DIR="$(mktemp -d "${MISE_BIN_DIR}/.mise-download.XXXXXXXX")"
  download_path="${DOWNLOAD_TEMP_DIR}/${asset_name}"
  trap cleanup_download EXIT
  trap 'cleanup_download; exit 129' HUP
  trap 'cleanup_download; exit 130' INT
  trap 'cleanup_download; exit 143' TERM

  printf 'Downloading mise %s for %s-%s...\n' "${MISE_VERSION}" "${OS_NAME}" "${ARCH_NAME}"
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
    --output "${download_path}" "${download_url}"

  actual_checksum="$(sha256_file "${download_path}")"
  [[ "${actual_checksum}" == "${MISE_CHECKSUM}" ]] ||
    fail "Checksum verification failed for ${asset_name}; expected ${MISE_CHECKSUM}, got ${actual_checksum}."

  chmod 0755 "${download_path}"
  mv -f -- "${download_path}" "${MISE_BIN}"
  cleanup_download
  trap - EXIT HUP INT TERM
  require_verified_mise
}

assert_tool_version() {
  local tool expected output actual
  tool="$1"
  expected="$2"

  case "${tool}" in
    python)
      output="$(run_mise exec -- python --version 2>&1)"
      actual="${output#Python }"
      ;;
    node)
      output="$(run_mise exec -- node --version 2>&1)"
      actual="${output#v}"
      ;;
    terraform)
      output="$(run_mise exec -- terraform version 2>&1)"
      actual="$(printf '%s\n' "${output}" | awk 'NR == 1 {sub(/^Terraform v/, ""); print; exit}')"
      ;;
    task)
      output="$(run_mise exec -- task --version 2>&1)"
      actual="$(printf '%s\n' "${output}" | awk '{for (i = 1; i <= NF; i++) if ($i ~ /^v?[0-9]+\.[0-9]+\.[0-9]+$/) {sub(/^v/, "", $i); print $i; exit}}')"
      ;;
    *)
      fail "Internal error: unknown tool '${tool}'."
      ;;
  esac

  [[ "${actual}" == "${expected}" ]] ||
    fail "${tool} version mismatch: expected ${expected}, got '${actual:-unrecognized}' (output: ${output})."
  printf 'Verified %s %s.\n' "${tool}" "${expected}"
}

verify_tools() {
  validate_all_managed_paths
  require_verified_mise

  (
    cd -- "${REPOSITORY_ROOT}"
    assert_tool_version python "${PYTHON_VERSION}"
    assert_tool_version node "${NODE_VERSION}"
    assert_tool_version terraform "${TERRAFORM_VERSION}"
    assert_tool_version task "${TASK_VERSION}"
  )
}

print_env() {
  local variable_name
  for variable_name in "${INHERITED_MISE_VARIABLES[@]}"; do
    printf 'unset %q\n' "${variable_name}"
  done
  printf 'export MISE_DATA_DIR=%q\n' "${MISE_DATA_DIR}"
  printf 'export MISE_CACHE_DIR=%q\n' "${MISE_CACHE_DIR}"
  printf 'export MISE_STATE_DIR=%q\n' "${MISE_STATE_DIR}"
  printf 'export MISE_CONFIG_DIR=%q\n' "${MISE_CONFIG_DIR}"
  printf 'export MISE_GLOBAL_CONFIG_FILE=/dev/null\n'
  printf 'export MISE_AUTO_INSTALL=0\n'
  printf 'export MISE_PYTHON_COMPILE=0\n'
  printf 'export MISE_PYTHON_GITHUB_ATTESTATIONS=false\n'
  printf 'export PATH=%q:%q:%sPATH\n' "${MISE_BIN_DIR}" "${MISE_SHIMS_DIR}" "\$"
}

if (($# >= 1)) && [[ "$1" == "--exec" ]]; then
  shift
  (($# >= 1)) || fail "--exec requires a command."
  MODE="exec"
  EXEC_COMMAND=("$@")
elif (($# > 1)); then
  usage >&2
  exit 2
elif (($# == 1)); then
  case "$1" in
    --dry-run)
      MODE="dry-run"
      ;;
    --verify)
      MODE="verify"
      ;;
    --env)
      MODE="env"
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
fi

validate_all_managed_paths
if [[ "${MODE}" == "env" ]]; then
  print_env
  exit 0
fi

require_command git
require_command curl
require_command uname
require_command awk
detect_platform
validate_all_managed_paths

if [[ "${MODE}" == "dry-run" ]]; then
  printf 'Host supported: %s-%s.\n' "${OS_NAME}" "${ARCH_NAME}"
  printf 'Would install mise %s at %s after SHA-256 verification.\n' "${MISE_VERSION}" "${MISE_BIN}"
  printf 'Would install and verify Python %s, Node.js %s, Terraform %s, and Task %s from %s.\n' \
    "${PYTHON_VERSION}" "${NODE_VERSION}" "${TERRAFORM_VERSION}" "${TASK_VERSION}" \
    "${REPOSITORY_ROOT}/mise.toml"
  exit 0
fi

if [[ "${MODE}" == "verify" ]]; then
  verify_tools
  exit 0
fi

if [[ "${MODE}" == "exec" ]]; then
  require_verified_mise
  exec "${MISE_BIN}" exec -- "${EXEC_COMMAND[@]}"
fi

install_mise
(
  cd -- "${REPOSITORY_ROOT}"
  run_mise trust --yes "${REPOSITORY_ROOT}/mise.toml"
  run_mise install
  run_mise reshim
)
verify_tools

printf '\nBootstrap complete. Run repository tasks without changing the parent PATH:\n'
printf '  %q --exec task setup\n' "${REPOSITORY_ROOT}/scripts/bootstrap.sh"
printf '  %q --exec task check\n' "${REPOSITORY_ROOT}/scripts/bootstrap.sh"
printf 'Or activate the repository tools in this shell with:\n'
printf '  eval "%s(%q --env)%s\n' "\$" "${REPOSITORY_ROOT}/scripts/bootstrap.sh" '"'
