#!/usr/bin/env bash
# Локальный прогон тех же проверок, что job `tests` в .github/workflows/tests.yml (CI).
#
# Виртуальное окружение .venv НЕ удаляется и не «сбрасывается»: скрипт только
# при необходимости делает pip install внутрь существующего .venv (как в CI).
#
# Перед первым запуском:
#   python3 -m venv .venv && . .venv/bin/activate
#   pip install -r requirements.txt  # или requirements.lock
#   pip install pytest pytest-asyncio coverage pip-audit
#
# Запуск из корня репозитория core-runtime-service:
#   ./scripts/ci_local.sh
#
# Опции:
#   --no-install   не вызывать pip install (депсы уже в .venv)
#   --no-audit     пропустить pip-audit (быстрее)
#   --no-coverage  pytest без coverage (быстрее)
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PY="${ROOT_DIR}/scripts/py_venv.sh"

DO_INSTALL=1
DO_AUDIT=1
DO_COVERAGE=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-install) DO_INSTALL=0 ;;
    --no-audit) DO_AUDIT=0 ;;
    --no-coverage) DO_COVERAGE=0 ;;
    -h|--help)
      sed -n '1,25p' "$0"
      exit 0
      ;;
    *)
      echo "Неизвестный аргумент: $1" >&2
      exit 2
      ;;
  esac
  shift
done

echo "==> CI local (как GitHub Actions: tests) — root: ${ROOT_DIR}"

if [[ "${DO_INSTALL}" -eq 1 ]]; then
  echo ""
  echo "==> [install] pip / requirements + инструменты как в CI"
  "${PY}" -- -m pip install -q --upgrade pip
  if [[ -f "${ROOT_DIR}/requirements.lock" ]]; then
    "${PY}" -- -m pip install -q -r "${ROOT_DIR}/requirements.lock"
  else
    "${PY}" -- -m pip install -q -r "${ROOT_DIR}/requirements.txt"
  fi
  "${PY}" -- -m pip install -q pytest pytest-asyncio coverage pip-audit
fi

if [[ "${DO_AUDIT}" -eq 1 ]]; then
  echo ""
  echo "==> [pip-audit] как в CI"
  PIP_AUDIT="${ROOT_DIR}/.venv/bin/pip-audit"
  if [[ ! -x "${PIP_AUDIT}" ]]; then
    echo "ERROR: нет ${PIP_AUDIT}. Убери --no-install или выполни: pip install pip-audit" >&2
    exit 2
  fi
  if [[ -f "${ROOT_DIR}/requirements.lock" ]]; then
    "${PIP_AUDIT}" -r "${ROOT_DIR}/requirements.lock"
  else
    "${PIP_AUDIT}" -r "${ROOT_DIR}/requirements.txt"
  fi
fi

echo ""
echo "==> [validate_architecture_rules] --enforce"
"${PY}" -- "${ROOT_DIR}/scripts/validate_architecture_rules.py" --root "${ROOT_DIR}" --enforce

echo ""
echo "==> [validate_plugin_sdk_imports] --enforce"
"${PY}" -- "${ROOT_DIR}/scripts/validate_plugin_sdk_imports.py" --root "${ROOT_DIR}" --enforce

echo ""
echo "==> [validate_plugin_sdk_usage] --enforce"
"${PY}" -- "${ROOT_DIR}/scripts/validate_plugin_sdk_usage.py" --root "${ROOT_DIR}" --enforce

if [[ "${DO_COVERAGE}" -eq 1 ]]; then
  echo ""
  echo "==> [pytest + coverage] как в CI"
  "${PY}" -- -m coverage run -m pytest -q
  "${PY}" -- -m coverage xml -i
  echo "OK: coverage.xml обновлён."
else
  echo ""
  echo "==> [pytest] без coverage"
  "${PY}" -- -m pytest -q
fi

echo ""
echo "OK: локальный CI-прогон завершён успешно."
