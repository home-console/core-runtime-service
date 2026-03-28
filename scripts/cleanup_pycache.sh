#!/usr/bin/env bash
# =============================================================================
# cleanup_pycache.sh — remove Python cache artifacts from repository tree
#
# Usage:
#   ./scripts/cleanup_pycache.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_DIR}"

echo "[CLEAN] Project: ${PROJECT_DIR}"

before_dirs=$(find . \
  -type d \( -name .git -o -name .venv -o -name .pytest_cache \) -prune -o \
  -type d -name '__pycache__' -print | wc -l | tr -d ' ')

before_files=$(find . \
  -type d \( -name .git -o -name .venv -o -name .pytest_cache \) -prune -o \
  -type f \( -name '*.pyc' -o -name '*.pyo' \) -print | wc -l | tr -d ' ')

find . \
  -type d \( -name .git -o -name .venv -o -name .pytest_cache \) -prune -o \
  -type d -name '__pycache__' -exec rm -rf {} +

find . \
  -type d \( -name .git -o -name .venv -o -name .pytest_cache \) -prune -o \
  -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

after_dirs=$(find . \
  -type d \( -name .git -o -name .venv -o -name .pytest_cache \) -prune -o \
  -type d -name '__pycache__' -print | wc -l | tr -d ' ')

after_files=$(find . \
  -type d \( -name .git -o -name .venv -o -name .pytest_cache \) -prune -o \
  -type f \( -name '*.pyc' -o -name '*.pyo' \) -print | wc -l | tr -d ' ')

echo "[CLEAN] __pycache__ dirs: ${before_dirs} -> ${after_dirs}"
echo "[CLEAN] .pyc/.pyo files: ${before_files} -> ${after_files}"
echo "[CLEAN] Done"
