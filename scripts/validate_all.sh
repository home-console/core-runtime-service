#!/usr/bin/env bash
set -euo pipefail

# Быстрые гарды (validators). Полный прогон как в GitHub Actions см.:
#   scripts/ci_local.sh
#
# Single entrypoint for local validation (Python >= 3.11 via .venv).
#
# Runs (by default):
# - architecture dependency guard
# - plugin SDK import guard
# - plugin SDK usage guard
#
# Usage:
#   scripts/validate_all.sh
#
# Optional:
#   scripts/validate_all.sh --with-tests

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${ROOT_DIR}/scripts/py_venv.sh"

cd "${ROOT_DIR}"

WITH_TESTS=0
if [[ "${1:-}" == "--with-tests" ]]; then
  WITH_TESTS=1
fi

echo "[1/4] Architecture guard"
"${PY}" -- "${ROOT_DIR}/scripts/validate_architecture_rules.py" --root "${ROOT_DIR}" --enforce
echo ""

echo "[2/4] Plugin SDK import guard"
"${PY}" -- "${ROOT_DIR}/scripts/validate_plugin_sdk_imports.py" --root "${ROOT_DIR}" --enforce
echo ""

echo "[3/4] Plugin SDK usage guard"
"${PY}" -- "${ROOT_DIR}/scripts/validate_plugin_sdk_usage.py" --root "${ROOT_DIR}" --enforce
echo ""

if [[ "${WITH_TESTS}" -eq 1 ]]; then
  echo "[4/4] Pytest"
  "${PY}" -- -m pytest -q
  echo ""
  echo "OK: all checks passed (including tests)."
  exit 0
fi

echo ""
echo "OK: guards passed. (Run with --with-tests to include pytest.)"

