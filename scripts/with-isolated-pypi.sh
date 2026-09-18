#!/usr/bin/env bash
# Run Python packaging tools without ambient pip indexes or user configuration.

set -euo pipefail

if (($# == 0)); then
  echo "Usage: with-isolated-pypi.sh PYTHON [ARG ...]" >&2
  exit 2
fi

python_executable="$1"
shift

# Use the selected Python interpreter to filter the environment as a mapping.
# This safely removes even unusual environment names that Bash cannot unset.
exec "${python_executable}" -c '
import os
import sys

environment = {
    name: value
    for name, value in os.environ.items()
    if not name.startswith("PIP_")
}
environment.update(
    {
        "PIP_CONFIG_FILE": "/dev/null",
        "PIP_INDEX_URL": "https://pypi.org/simple",
        "PIP_EXTRA_INDEX_URL": "",
    }
)
os.execvpe(sys.argv[1], sys.argv[1:], environment)
' "${python_executable}" "$@"
