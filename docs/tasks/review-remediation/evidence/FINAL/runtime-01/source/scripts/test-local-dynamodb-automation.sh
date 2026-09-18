#!/usr/bin/env bash

set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
automation="${root_dir}/scripts/local-dynamodb.sh"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

identity="$(DYNAMODB_LOCAL_PORT=18001 "${automation}" identity)"
same_identity="$(DYNAMODB_LOCAL_PORT=18001 "${automation}" identity)"
other_port_identity="$(DYNAMODB_LOCAL_PORT=18002 "${automation}" identity)"

[[ "${identity}" == "${same_identity}" ]]
[[ "${identity}" != "${other_port_identity}" ]]
[[ "${identity}" =~ ^[a-z0-9][a-z0-9_-]*$ ]]
[[ "${#identity}" -le 63 ]]

mkdir -p "${tmp_dir}/other-worktree/scripts"
cp "${automation}" "${tmp_dir}/other-worktree/scripts/local-dynamodb.sh"
cp "${root_dir}/compose.yaml" "${tmp_dir}/other-worktree/compose.yaml"
other_worktree_identity="$(
  DYNAMODB_LOCAL_PORT=18001 \
    "${tmp_dir}/other-worktree/scripts/local-dynamodb.sh" identity
)"
[[ "${identity}" != "${other_worktree_identity}" ]]

cat >"${tmp_dir}/other-worktree/.env" <<'EOF'
DYNAMODB_LOCAL_PORT=29999
EOF
config="$(
  DYNAMODB_LOCAL_PORT=19001 \
    "${tmp_dir}/other-worktree/scripts/local-dynamodb.sh" config
)"
grep -q 'published: "19001"' <<<"${config}"
if grep -q '29999' <<<"${config}"; then
  echo "Root .env overrode the validated DynamoDB port." >&2
  exit 1
fi

invalid_ports=(
  ""
  "0"
  "00"
  "01"
  "+1"
  "-1"
  " 1"
  "1 "
  "65536"
  "999999"
  "999999999999999999999999999999999999999999999999999999999999"
  "1e3"
  "abc"
)
for invalid_port in "${invalid_ports[@]}"; do
  if DYNAMODB_LOCAL_PORT="${invalid_port}" "${automation}" identity >/dev/null 2>&1; then
    printf 'Invalid DYNAMODB_LOCAL_PORT was accepted: <%s>\n' "${invalid_port}" >&2
    exit 1
  fi
done

for valid_port in 1 9 10 18000 65535; do
  DYNAMODB_LOCAL_PORT="${valid_port}" "${automation}" identity >/dev/null
done

echo "Local DynamoDB automation regression tests passed."
