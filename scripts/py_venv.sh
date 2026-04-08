#!/usr/bin/env bash
set -euo pipefail

# Run python from core-runtime-service/.venv with version guard (>= 3.11).
#
# Usage:
#   scripts/py_venv.sh -- <python args...>
# Examples:
#   scripts/py_venv.sh -- scripts/validate_architecture_rules.py --root .
#   scripts/py_venv.sh -- -m pytest -q

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="${ROOT_DIR}/.venv/bin/python"

if [[ ! -x "${VENV_PY}" ]]; then
  echo "ERROR: ${VENV_PY} not found/executable."
  echo "Create venv in core-runtime-service/.venv with Python >= 3.11."
  exit 2
fi

PY_VER="$("${VENV_PY}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJ="${PY_VER%%.*}"
PY_MIN="${PY_VER#*.}"

if [[ "${PY_MAJ}" -lt 3 || ( "${PY_MAJ}" -eq 3 && "${PY_MIN}" -lt 11 ) ]]; then
  echo "ERROR: .venv python is ${PY_VER}, need >= 3.11."
  exit 2
fi

if [[ "${1:-}" == "--" ]]; then
  shift
fi

exec "${VENV_PY}" "$@"

