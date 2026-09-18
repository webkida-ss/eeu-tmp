#!/bin/bash
set -euo pipefail

export PATH="/usr/bin:/bin:/usr/sbin:/sbin"
unset BASH_ENV CDPATH ENV GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM

readonly VERSION="1.23.0"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly ROOT
readonly LOCK_FILE="${ROOT}/scripts/tool-locks/oasdiff/checksums.tsv"
readonly TOOLS_ROOT="${REPOSITORY_TOOLS_DIR:-${ROOT}/.tools}"
readonly INSTALL_ROOT="${TOOLS_ROOT}/oasdiff/${VERSION}"
readonly BIN_DIR="${INSTALL_ROOT}/bin"
readonly BIN="${BIN_DIR}/oasdiff"
ARCHIVE_OVERRIDE=""
MODE="install"
TEMP_DIR=""

fail() {
  printf 'oasdiff installer: error: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [[ -n "${TEMP_DIR}" && -d "${TEMP_DIR}" ]]; then
    rm -rf -- "${TEMP_DIR}"
  fi
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  else
    fail "A SHA-256 utility is required."
  fi
}

validate_path() {
  local path="$1" relative current component
  [[ "${path}" == "${ROOT}/"* ]] || fail "Managed path escapes repository: ${path}"
  relative="${path#"${ROOT}/"}"
  current="${ROOT}"
  while [[ -n "${relative}" ]]; do
    component="${relative%%/*}"
    [[ "${component}" == "${relative}" ]] && relative="" || relative="${relative#*/}"
    [[ -n "${component}" && "${component}" != "." && "${component}" != ".." ]] ||
      fail "Unsafe managed path: ${path}"
    current="${current}/${component}"
    [[ ! -L "${current}" ]] || fail "Managed path component is a symlink: ${current}"
  done
}

platform() {
  local os arch
  case "$(uname -s)" in
    Darwin) os="darwin" ;;
    Linux) os="linux" ;;
    *) fail "Unsupported operating system: $(uname -s)" ;;
  esac
  case "$(uname -m)" in
    arm64 | aarch64) arch="arm64" ;;
    x86_64 | amd64) arch="x64" ;;
    *) fail "Unsupported architecture: $(uname -m)" ;;
  esac
  printf '%s-%s\n' "${os}" "${arch}"
}

lookup_lock() {
  local key="$1"
  awk -F '\t' -v key="${key}" '
    NR > 1 && $1 == key {
      if (found++) exit 2
      print $2 "\t" $3 "\t" $4
    }
    END {
      if (found != 1) exit 1
    }
  ' "${LOCK_FILE}" || fail "Exactly one checksum lock is required for ${key}."
}

verify_installed() {
  local expected="$1"
  validate_path "${BIN}"
  [[ -f "${BIN}" && ! -L "${BIN}" && -x "${BIN}" ]] ||
    fail "Verified binary is not installed at ${BIN}."
  [[ "$(sha256_file "${BIN}")" == "${expected}" ]] ||
    fail "Installed oasdiff binary checksum does not match the lock."
  "${BIN}" --version | grep -F "${VERSION}" >/dev/null ||
    fail "Installed oasdiff version does not match ${VERSION}."
}

while (($#)); do
  case "$1" in
    --verify) MODE="verify" ;;
    --archive)
      shift
      (($#)) || fail "--archive requires a path."
      ARCHIVE_OVERRIDE="$1"
      ;;
    -h | --help)
      printf 'Usage: scripts/install-oasdiff.sh [--verify] [--archive FILE]\n'
      exit 0
      ;;
    *) fail "Unknown argument: $1" ;;
  esac
  shift
done

command -v awk >/dev/null || fail "awk is required."
[[ -f "${LOCK_FILE}" && ! -L "${LOCK_FILE}" ]] || fail "Checksum lock is missing or unsafe."
read -r ASSET EXPECTED_ARCHIVE_SHA EXPECTED_BINARY_SHA <<<"$(lookup_lock "$(platform)")"
[[ "${EXPECTED_ARCHIVE_SHA}" =~ ^[0-9a-f]{64}$ ]] || fail "Invalid locked checksum."
[[ "${EXPECTED_BINARY_SHA}" =~ ^[0-9a-f]{64}$ ]] || fail "Invalid locked binary checksum."

if [[ "${MODE}" == "verify" ]]; then
  verify_installed "${EXPECTED_BINARY_SHA}"
  exit 0
fi

validate_path "${INSTALL_ROOT}"
validate_path "${BIN_DIR}"
validate_path "${BIN}"
if [[ -z "${ARCHIVE_OVERRIDE}" && -f "${BIN}" && ! -L "${BIN}" && "$(sha256_file "${BIN}")" == "${EXPECTED_BINARY_SHA}" ]]; then
  verify_installed "${EXPECTED_BINARY_SHA}"
  printf 'Checksum-verified oasdiff %s is already installed at %s\n' "${VERSION}" "${BIN}"
  exit 0
fi
mkdir -p "${BIN_DIR}"
validate_path "${BIN_DIR}"
TEMP_DIR="$(mktemp -d "${INSTALL_ROOT}/.install.XXXXXXXX")"
trap cleanup EXIT HUP INT TERM
ARCHIVE="${TEMP_DIR}/${ASSET}"

if [[ -n "${ARCHIVE_OVERRIDE}" ]]; then
  [[ -f "${ARCHIVE_OVERRIDE}" && ! -L "${ARCHIVE_OVERRIDE}" ]] ||
    fail "Archive override must be a regular non-symlink file."
  cp -- "${ARCHIVE_OVERRIDE}" "${ARCHIVE}"
else
  command -v curl >/dev/null || fail "curl is required."
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
    --output "${ARCHIVE}" \
    "https://github.com/Tufin/oasdiff/releases/download/v${VERSION}/${ASSET}"
fi

ACTUAL_ARCHIVE_SHA="$(sha256_file "${ARCHIVE}")"
[[ "${ACTUAL_ARCHIVE_SHA}" == "${EXPECTED_ARCHIVE_SHA}" ]] ||
  fail "Archive checksum mismatch; expected ${EXPECTED_ARCHIVE_SHA}, got ${ACTUAL_ARCHIVE_SHA}."

command -v tar >/dev/null || fail "tar is required."
tar -xzf "${ARCHIVE}" -C "${TEMP_DIR}" oasdiff
[[ -f "${TEMP_DIR}/oasdiff" && ! -L "${TEMP_DIR}/oasdiff" ]] ||
  fail "Archive did not contain a regular oasdiff binary."
chmod 0755 "${TEMP_DIR}/oasdiff"
[[ "$(sha256_file "${TEMP_DIR}/oasdiff")" == "${EXPECTED_BINARY_SHA}" ]] ||
  fail "Extracted oasdiff binary checksum does not match the lock."
"${TEMP_DIR}/oasdiff" --version | grep -F "${VERSION}" >/dev/null ||
  fail "Downloaded binary version does not match ${VERSION}."
mv -f -- "${TEMP_DIR}/oasdiff" "${BIN}"
cleanup
trap - EXIT HUP INT TERM
verify_installed "${EXPECTED_BINARY_SHA}"
printf 'Installed checksum-verified oasdiff %s at %s\n' "${VERSION}" "${BIN}"
