#!/bin/sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
case "${BACKEND_VENV:-backend/.venv}" in
  backend/.venv | backend/.devcontainer-venv)
    python="${repository_root}/${BACKEND_VENV:-backend/.venv}/bin/python"
    ;;
  *)
    exit 0
    ;;
esac

# Hooks must not break an edit before managed development tools are installed.
if [ ! -x "${python}" ]; then
  exit 0
fi

exec "${python}" "${repository_root}/.rulesync/hooks/format.py"
