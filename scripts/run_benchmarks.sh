#!/usr/bin/env bash
# =============================================================================
# run_benchmarks.sh — HomeConsole Benchmark Runner
# Day 5: Performance Benchmarks orchestration script
#
# Usage:
#   ./scripts/run_benchmarks.sh                 # run all benchmarks
#   ./scripts/run_benchmarks.sh --memory        # memory profiling only
#   ./scripts/run_benchmarks.sh --storage       # storage benchmarks only
#   ./scripts/run_benchmarks.sh --k6            # K6 load tests only
#   ./scripts/run_benchmarks.sh --all           # explicit all
#   ./scripts/run_benchmarks.sh --report-only   # skip tests, open last report
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPORTS_DIR="${PROJECT_DIR}/tests/performance/reports"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
REPORT_FILE="${REPORTS_DIR}/benchmark_${TIMESTAMP}.json"
HTML_REPORT="${REPORTS_DIR}/benchmark_${TIMESTAMP}.html"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'
BOLD='\033[1m'; RESET='\033[0m'

log()   { echo -e "${BLUE}[BENCH]${RESET} $*"; }
ok()    { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*" >&2; }
fail()  { echo -e "${RED}[FAIL]${RESET}  $*" >&2; }
title() { echo -e "\n${BOLD}${BLUE}══════════════════════════════════════${RESET}"; \
          echo -e "${BOLD}  $*${RESET}"; \
          echo -e "${BOLD}${BLUE}══════════════════════════════════════${RESET}\n"; }

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
RUN_MEMORY=0
RUN_STORAGE=0
RUN_K6=0
REPORT_ONLY=0

if [[ $# -eq 0 ]]; then
  RUN_MEMORY=1; RUN_STORAGE=1; RUN_K6=0
else
  for arg in "$@"; do
    case "$arg" in
      --memory)      RUN_MEMORY=1 ;;
      --storage)     RUN_STORAGE=1 ;;
      --k6)          RUN_K6=1 ;;
      --all)         RUN_MEMORY=1; RUN_STORAGE=1; RUN_K6=1 ;;
      --report-only) REPORT_ONLY=1 ;;
      *)             warn "Unknown flag: $arg"; ;;
    esac
  done
fi

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
setup() {
  title "HomeConsole Benchmark Runner v1.0"
  log "Project dir : ${PROJECT_DIR}"
  log "Reports dir : ${REPORTS_DIR}"
  log "Timestamp   : ${TIMESTAMP}"

  mkdir -p "${REPORTS_DIR}"

  cd "${PROJECT_DIR}"

  # Activate venv if present
  if [[ -f "${PROJECT_DIR}/../.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "${PROJECT_DIR}/../.venv/bin/activate"
    log "Python env  : $(python --version)"
  elif [[ -f "${PROJECT_DIR}/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "${PROJECT_DIR}/.venv/bin/activate"
    log "Python env  : $(python --version)"
  else
    warn "No .venv found — using system Python: $(python3 --version 2>/dev/null || echo 'not found')"
  fi
}

# ---------------------------------------------------------------------------
# Memory Profiling benchmarks
# ---------------------------------------------------------------------------
run_memory_benchmarks() {
  title "Memory Profiling Benchmarks"

  local out_json="${REPORTS_DIR}/memory_${TIMESTAMP}.json"
  local out_html="${REPORTS_DIR}/memory_${TIMESTAMP}.html"

  log "Running tests/benchmarks/test_memory_profiling.py ..."
  if python -m pytest tests/benchmarks/test_memory_profiling.py \
      -v \
      --tb=short \
      --timeout=120 \
      -p no:asyncio \
      --json-report --json-report-file="${out_json}" \
      -s 2>&1 | tee /tmp/bench_memory.log; then
    ok "Memory benchmarks PASSED → ${out_json}"
    MEMORY_STATUS="PASS"
  else
    fail "Memory benchmarks FAILED (see /tmp/bench_memory.log)"
    MEMORY_STATUS="FAIL"
  fi

  # Print [MEM] tagged lines
  echo ""
  log "Memory measurements:"
  grep -E '\[MEM\]' /tmp/bench_memory.log | sed 's/^/  /' || true
}

# ---------------------------------------------------------------------------
# Storage Performance benchmarks
# ---------------------------------------------------------------------------
run_storage_benchmarks() {
  title "Storage Performance Benchmarks"

  local out_json="${REPORTS_DIR}/storage_${TIMESTAMP}.json"

  log "Running tests/benchmarks/test_storage_performance.py ..."
  if python -m pytest tests/benchmarks/test_storage_performance.py \
      -v \
      --tb=short \
      --timeout=120 \
      -p no:asyncio \
      --json-report --json-report-file="${out_json}" \
      -s 2>&1 | tee /tmp/bench_storage.log; then
    ok "Storage benchmarks PASSED → ${out_json}"
    STORAGE_STATUS="PASS"
  else
    fail "Storage benchmarks FAILED"
    STORAGE_STATUS="FAIL"
  fi

  echo ""
  log "Throughput/latency measurements:"
  grep -E '\[(TPUT|LAT|SCALE)\]' /tmp/bench_storage.log | sed 's/^/  /' || true
}

# ---------------------------------------------------------------------------
# K6 Load Tests
# ---------------------------------------------------------------------------
run_k6_tests() {
  title "K6 Load Tests"

  if ! command -v k6 &>/dev/null; then
    warn "k6 not installed — skipping load tests."
    warn "Install: brew install k6  OR  https://k6.io/docs/getting-started/installation/"
    K6_STATUS="SKIP"
    return 0
  fi

  local k6_out="${REPORTS_DIR}/k6_${TIMESTAMP}.json"
  local base_url="${BASE_URL:-http://localhost:8000}"

  log "Target URL  : ${base_url}"
  log "Output file : ${k6_out}"

  # Check if the server is reachable
  if ! curl -sf "${base_url}/health" &>/dev/null; then
    warn "Server at ${base_url} is not reachable."
    warn "Start the server first:  uvicorn main:app --port 8000"
    warn "Then re-run:  BASE_URL=${base_url} ./scripts/run_benchmarks.sh --k6"
    K6_STATUS="SKIP"
    return 0
  fi

  if BASE_URL="${base_url}" \
     DURATION="${K6_DURATION:-30s}" \
     VUS="${K6_VUS:-10}" \
     k6 run \
       --out json="${k6_out}" \
       tests/performance/k6_load_test.js 2>&1 | tee /tmp/bench_k6.log; then
    ok "K6 load tests PASSED → ${k6_out}"
    K6_STATUS="PASS"
  else
    fail "K6 load tests FAILED"
    K6_STATUS="FAIL"
  fi
}

# ---------------------------------------------------------------------------
# Generate HTML report
# ---------------------------------------------------------------------------
generate_html_report() {
  title "Generating HTML Report"

  local mem_log=/tmp/bench_memory.log
  local storage_log=/tmp/bench_storage.log

  # Extract measurements
  local mem_lines="" storage_lines=""
  [[ -f "$mem_log" ]] && mem_lines=$(grep -E '\[MEM\]' "$mem_log" | sed 's/^/          /' || true)
  [[ -f "$storage_log" ]] && storage_lines=$(grep -E '\[(TPUT|LAT|SCALE)\]' "$storage_log" | sed 's/^/          /' || true)

  cat > "${HTML_REPORT}" <<HTML
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <title>HomeConsole Benchmark Report — ${TIMESTAMP}</title>
  <style>
    body { font-family: monospace; background: #1a1a2e; color: #eee; max-width: 900px; margin: 0 auto; padding: 20px; }
    h1 { color: #16213e; background: #0f3460; padding: 12px; border-radius: 6px; }
    h2 { color: #e94560; margin-top: 30px; }
    .pass { color: #00ff88; font-weight: bold; }
    .fail { color: #ff4466; font-weight: bold; }
    .skip { color: #ffaa00; font-weight: bold; }
    pre { background: #0f0f1a; padding: 15px; border-radius: 6px; overflow-x: auto; font-size: 13px; }
    .meta { color: #888; font-size: 12px; }
    table { width: 100%; border-collapse: collapse; margin: 10px 0; }
    th { background: #0f3460; padding: 8px; text-align: left; }
    td { padding: 6px 8px; border-bottom: 1px solid #333; }
  </style>
</head>
<body>
  <h1>🏠 HomeConsole Benchmark Report</h1>
  <p class="meta">Generated: ${TIMESTAMP} | Project: core-runtime-service</p>

  <h2>Summary</h2>
  <table>
    <tr><th>Suite</th><th>Status</th></tr>
    <tr><td>Memory Profiling</td><td class="${MEMORY_STATUS,,}">${MEMORY_STATUS:-SKIP}</td></tr>
    <tr><td>Storage Performance</td><td class="${STORAGE_STATUS,,}">${STORAGE_STATUS:-SKIP}</td></tr>
    <tr><td>K6 Load Tests</td><td class="${K6_STATUS,,}">${K6_STATUS:-SKIP}</td></tr>
  </table>

  <h2>Memory Profiling Results</h2>
  <pre>${mem_lines:-No data (not run)}</pre>

  <h2>Storage Performance Results</h2>
  <pre>${storage_lines:-No data (not run)}</pre>

  <h2>K6 Results</h2>
  <pre>$(cat /tmp/bench_k6.log 2>/dev/null | tail -50 || echo "Not run")</pre>

  <p class="meta">Reports dir: ${REPORTS_DIR}</p>
</body>
</html>
HTML

  ok "HTML report → ${HTML_REPORT}"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

MEMORY_STATUS="SKIP"
STORAGE_STATUS="SKIP"
K6_STATUS="SKIP"

if [[ "$REPORT_ONLY" -eq 1 ]]; then
  log "Opening last HTML report..."
  LAST=$(ls -t "${REPORTS_DIR}"/benchmark_*.html 2>/dev/null | head -1)
  if [[ -n "$LAST" ]]; then
    open "$LAST" 2>/dev/null || xdg-open "$LAST" 2>/dev/null || log "Report: $LAST"
  else
    warn "No HTML reports found in ${REPORTS_DIR}"
  fi
  exit 0
fi

setup

[[ "$RUN_MEMORY" -eq 1 ]] && run_memory_benchmarks
[[ "$RUN_STORAGE" -eq 1 ]] && run_storage_benchmarks
[[ "$RUN_K6" -eq 1 ]] && run_k6_tests

generate_html_report

title "Results"
echo -e "  Memory     : $([ "$MEMORY_STATUS" = PASS ] && echo "${GREEN}PASS${RESET}" || echo "${YELLOW}${MEMORY_STATUS}${RESET}")"
echo -e "  Storage    : $([ "$STORAGE_STATUS" = PASS ] && echo "${GREEN}PASS${RESET}" || echo "${YELLOW}${STORAGE_STATUS}${RESET}")"
echo -e "  K6         : $([ "$K6_STATUS" = PASS ] && echo "${GREEN}PASS${RESET}" || echo "${YELLOW}${K6_STATUS}${RESET}")"
echo ""
log "HTML report: ${HTML_REPORT}"

# Exit non-zero if any required test failed
if [[ "$MEMORY_STATUS" = "FAIL" || "$STORAGE_STATUS" = "FAIL" || "$K6_STATUS" = "FAIL" ]]; then
  exit 1
fi
exit 0
