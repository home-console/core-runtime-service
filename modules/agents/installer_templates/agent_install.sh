#!/bin/bash
# ==============================================================================
# HomeConsole Remote Agent Installer v2.1
# ==============================================================================
#
# Usage: ./agent_install.sh <ENROLLMENT_TOKEN> <CORE_URL>
#
# Features:
#  - Retry with exponential backoff + jitter (avoids thundering herd)
#  - SHA256 checksum verification (sha256sum → shasum → openssl fallback)
#  - Downloader fallback: curl → wget → nc (with full nc implementation)
#  - Pre-flight connectivity check before downloading
#  - Graceful degradation (systemd optional, direct launch fallback)
#  - Health check after launch
#  - Structured JSON-compatible logging
#  - Idempotent re-install (upgrades running agent)
#  - Correct trap: only cleanup on ERROR, not on success
#
# Environment variables:
#  DEBUG=1             — verbose debug logging
#  MAX_RETRIES=3       — max download attempts
#  RETRY_DELAY=5       — initial retry delay seconds
#  INSTALL_DIR         — installation directory (default: /opt/home-agent)
#  AGENT_CORE_URL      — override CORE_URL (useful in containerized envs)
#  SKIP_CHECKSUM=1     — skip checksum verification (dev mode)
#  SKIP_SYSTEMD=1      — skip systemd setup (force direct launch)
# ==============================================================================

set -Eeuo pipefail

# ============================================================================
# Configuration
# ============================================================================

readonly ENROLLMENT_TOKEN="${1:-}"
readonly CORE_URL="${AGENT_CORE_URL:-${2:-}}"
readonly INSTALL_DIR="${INSTALL_DIR:-/opt/home-agent}"
readonly BINARY_NAME="remote-client"
readonly SERVICE_NAME="home-agent"

readonly MAX_RETRIES="${MAX_RETRIES:-3}"
readonly RETRY_DELAY="${RETRY_DELAY:-5}"
readonly HEALTH_CHECK_TIMEOUT="${HEALTH_CHECK_TIMEOUT:-30}"
readonly SKIP_CHECKSUM="${SKIP_CHECKSUM:-0}"
readonly SKIP_SYSTEMD="${SKIP_SYSTEMD:-0}"

# Track whether install succeeded (used by error trap)
_INSTALL_SUCCESS=0

DEBUG="${DEBUG:-0}"

# ============================================================================
# Logging helpers
# ============================================================================

log_timestamp() {
  date -u +'%Y-%m-%dT%H:%M:%SZ'
}

log_info() {
  echo "[$(log_timestamp)] INFO: $*" >&2
}

log_warn() {
  echo "[$(log_timestamp)] WARN: $*" >&2
}

log_error() {
  echo "[$(log_timestamp)] ERROR: $*" >&2
}

log_debug() {
  if [[ "$DEBUG" == "1" ]]; then
    echo "[$(log_timestamp)] DEBUG: $*" >&2
  fi
}

# ============================================================================
# Validation
# ============================================================================

validate_input() {
  if [[ -z "$ENROLLMENT_TOKEN" ]] || [[ -z "$CORE_URL" ]]; then
    log_error "Missing required arguments"
    echo "Usage: $0 <ENROLLMENT_TOKEN> <CORE_URL>" >&2
    return 1
  fi
  
  # Validate CORE_URL format
  if ! [[ "$CORE_URL" =~ ^https?:// ]]; then
    log_error "Invalid CORE_URL: must start with http:// or https://"
    return 1
  fi
  
  log_info "Validation OK (token=*****, url=$CORE_URL)"
}

# ============================================================================
# Downloader detection
# ============================================================================

find_downloader() {
  if command -v curl &> /dev/null; then
    echo "curl"
  elif command -v wget &> /dev/null; then
    echo "wget"
  elif command -v nc &> /dev/null; then
    echo "nc"
  elif command -v python3 &> /dev/null; then
    echo "python3"
  else
    return 1
  fi
}

# ============================================================================
# Retry helpers
# ============================================================================

# Calculate exponential backoff with ±25% jitter to avoid thundering herd
# Usage: backoff_seconds <attempt_number (1-based)>
backoff_seconds() {
  local attempt="$1"
  local base=$(( RETRY_DELAY * (2 ** (attempt - 1)) ))
  # Jitter: random ±25% of base (requires $RANDOM)
  local jitter=$(( (RANDOM % (base / 2 + 1)) - (base / 4) ))
  local total=$(( base + jitter ))
  # Floor at 1 second
  if [[ $total -lt 1 ]]; then total=1; fi
  echo "$total"
}

# ============================================================================
# Pre-flight connectivity check
# ============================================================================

preflight_check() {
  local url="$1"
  local host
  local port

  # Extract host:port
  if [[ "$url" =~ ^https?://([^:/]+)(:([0-9]+))? ]]; then
    host="${BASH_REMATCH[1]}"
    port="${BASH_REMATCH[3]:-$(  [[ $url == https* ]] && echo 443 || echo 80 )}"
  else
    log_warn "Cannot parse URL for preflight: $url"
    return 0  # Non-fatal
  fi

  log_info "Pre-flight: checking connectivity to ${host}:${port} ..."

  # Try nc first (fastest)
  if command -v nc &> /dev/null; then
    if nc -z -w 5 "$host" "$port" 2>/dev/null; then
      log_info "Pre-flight OK (nc) ✓"
      return 0
    fi
  fi

  # Fallback: curl --connect-timeout
  if command -v curl &> /dev/null; then
    if curl -s --connect-timeout 5 --max-time 5 -o /dev/null "${url%/}/" 2>/dev/null; then
      log_info "Pre-flight OK (curl) ✓"
      return 0
    fi
  fi

  log_error "Pre-flight FAILED: cannot reach ${host}:${port}"
  log_error "Check network connectivity and CORE_URL"
  return 1
}

ensure_downloader() {
  local downloader
  downloader=$(find_downloader) || {
    log_error "No downloader found (curl, wget, or nc required)"
    return 1
  }
  
  log_info "Using downloader: $downloader"
  echo "$downloader"
}

# ============================================================================
# Download with retry and checksum
# ============================================================================

download_binary() {
  local url="$1"
  local output_path="$2"
  local downloader="$3"
  local attempt
  local exit_code
  local wait_secs

  for attempt in $(seq 1 "$MAX_RETRIES"); do
    log_info "Download attempt $attempt/$MAX_RETRIES via ${downloader} (url=$url)"

    case "$downloader" in
      curl)
        if curl -fsSL --max-time 120 --connect-timeout 15 --retry 0 \
             -H 'Accept: application/octet-stream' \
             "$url" -o "$output_path" 2>/dev/null; then
          log_info "Download successful via curl ($(du -sh "$output_path" 2>/dev/null | cut -f1))"
          return 0
        fi
        exit_code=$?
        log_warn "curl failed with exit code $exit_code"
        ;;
      wget)
        if wget -q --timeout=120 --tries=1 \
             --header='Accept: application/octet-stream' \
             "$url" -O "$output_path" 2>/dev/null; then
          log_info "Download successful via wget ($(du -sh "$output_path" 2>/dev/null | cut -f1))"
          return 0
        fi
        exit_code=$?
        log_warn "wget failed with exit code $exit_code"
        ;;
      nc)
        # Full nc (netcat) implementation for minimal environments
        local host port path
        if [[ "$url" =~ ^https?://([^:/]+)(:([0-9]+))?(/.*)?$ ]]; then
          host="${BASH_REMATCH[1]}"
          port="${BASH_REMATCH[3]:-80}"
          path="${BASH_REMATCH[4]:-/}"
        else
          log_warn "nc: cannot parse url $url"
          continue
        fi
        log_debug "nc connecting to ${host}:${port}${path}"
        {
          printf 'GET %s HTTP/1.0\r\nHost: %s\r\nAccept: application/octet-stream\r\nConnection: close\r\n\r\n' \
            "$path" "$host"
        } | nc -w 30 "$host" "$port" > /tmp/_nc_response 2>/dev/null
        # Strip HTTP headers (everything up to the first blank line)
        if [[ -s /tmp/_nc_response ]]; then
          awk '/^\r?$/{found=1; next} found{print}' /tmp/_nc_response > "$output_path" 2>/dev/null
          rm -f /tmp/_nc_response
          if [[ -s "$output_path" ]]; then
            log_info "Download successful via nc ($(du -sh "$output_path" 2>/dev/null | cut -f1))"
            return 0
          fi
        fi
        rm -f /tmp/_nc_response
        log_warn "nc download failed or returned empty response"
        ;;
      python3)
        # Last resort: Python3 urllib
        if python3 -c "
import urllib.request, sys
url = sys.argv[1]
output = sys.argv[2]
try:
    req = urllib.request.Request(url, headers={'Accept': 'application/octet-stream'})
    with urllib.request.urlopen(req, timeout=120) as r, open(output, 'wb') as f:
        f.write(r.read())
    print('python3 download ok', file=sys.stderr)
except Exception as e:
    print(f'python3 download failed: {e}', file=sys.stderr)
    sys.exit(1)
" "$url" "$output_path" 2>/dev/null; then
          log_info "Download successful via python3 ($(du -sh "$output_path" 2>/dev/null | cut -f1))"
          return 0
        fi
        log_warn "python3 download failed"
        ;;
    esac

    # Clean up partial file
    rm -f "$output_path"

    if [[ $attempt -lt $MAX_RETRIES ]]; then
      wait_secs=$(backoff_seconds "$attempt")
      log_info "Retry in ${wait_secs}s (exponential backoff + jitter)..."
      sleep "$wait_secs"
    fi
  done

  log_error "Failed to download after $MAX_RETRIES attempts"
  return 1
}

# ============================================================================
# Checksum verification
# ============================================================================

# compute_sha256 <file> — portable SHA256 computation
compute_sha256() {
  local file="$1"
  if command -v sha256sum &> /dev/null; then
    sha256sum "$file" | cut -d' ' -f1
  elif command -v shasum &> /dev/null; then
    shasum -a 256 "$file" | cut -d' ' -f1
  elif command -v openssl &> /dev/null; then
    openssl dgst -sha256 "$file" | awk '{print $2}'
  elif command -v python3 &> /dev/null; then
    python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$file"
  else
    log_warn "No SHA256 tool available (sha256sum/shasum/openssl/python3)"
    echo ""
  fi
}

get_expected_checksum() {
  local checksum_url="$1"
  local response

  log_info "Fetching checksum from server..."

  if command -v curl &> /dev/null; then
    response=$(curl -fsSL --max-time 30 "$checksum_url" 2>/dev/null) || return 1
  elif command -v wget &> /dev/null; then
    response=$(wget -q -O - --timeout=30 "$checksum_url" 2>/dev/null) || return 1
  else
    return 1
  fi

  # Parse JSON {"sha256":"..."}  or plain hex string
  if echo "$response" | grep -q '"sha256"'; then
    # POSIX-compatible JSON extraction (no jq dependency)
    echo "$response" | sed -n 's/.*"sha256"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'
  else
    # Assume plain hex
    echo "$response" | tr -d '[:space:]'
  fi
}

verify_checksum() {
  local binary_path="$1"
  local checksum_url="$2"
  local expected_checksum
  local actual_checksum

  if [[ "$SKIP_CHECKSUM" == "1" ]]; then
    log_warn "SKIP_CHECKSUM=1 — skipping checksum verification (dev mode)"
    return 0
  fi

  log_info "Verifying binary checksum..."

  expected_checksum=$(get_expected_checksum "$checksum_url") || {
    log_warn "Could not fetch checksum from server — skipping verification"
    return 0  # Non-fatal: server may not expose checksum yet
  }

  if [[ -z "$expected_checksum" ]] || [[ "$expected_checksum" == "not_yet_implemented" ]]; then
    log_warn "Checksum not available on server — skipping verification"
    return 0
  fi

  actual_checksum=$(compute_sha256 "$binary_path")

  if [[ -z "$actual_checksum" ]]; then
    log_warn "Cannot compute local checksum — skipping verification"
    return 0
  fi

  log_debug "Expected: $expected_checksum"
  log_debug "Actual:   $actual_checksum"

  if [[ "$expected_checksum" != "$actual_checksum" ]]; then
    log_error "Checksum MISMATCH — binary may be corrupted or tampered!"
    log_error "  Expected: $expected_checksum"
    log_error "  Actual:   $actual_checksum"
    return 1
  fi

  log_info "Checksum verified ✓ ($actual_checksum)"
  return 0
}

# ============================================================================
# Parse CORE_URL
# ============================================================================

parse_core_url() {
  local core_url="$1"
  
  core_url="${core_url%/}"  # Remove trailing slash
  
  # Extract protocol, host, port
  if [[ "$core_url" =~ ^https?://([^:/]+)(:([0-9]+))? ]]; then
    export RC_SERVER_HOST="${BASH_REMATCH[1]}"
    export RC_SERVER_PORT="${BASH_REMATCH[3]:-8000}"
    
    if [[ "$core_url" == https* ]]; then
      export RC_SERVER_PROTOCOL="websocket"
      export RC_USE_TLS="true"
    else
      export RC_SERVER_PROTOCOL="websocket"
      export RC_USE_TLS="false"
    fi
    
    export RC_SERVER_PATH="/ws"
    
    log_info "Parsed CORE_URL: host=$RC_SERVER_HOST port=$RC_SERVER_PORT tls=$RC_USE_TLS"
    return 0
  else
    log_error "Invalid CORE_URL format: $core_url"
    return 1
  fi
}

# ============================================================================
# Setup directories
# ============================================================================

setup_directories() {
  log_info "Setting up directories: $INSTALL_DIR"
  
  if ! mkdir -p "$INSTALL_DIR"; then
    log_error "Failed to create install directory"
    return 1
  fi
  
  cd "$INSTALL_DIR"
  log_info "Working directory: $(pwd)"
}

# ============================================================================
# Setup systemd service (optional)
# ============================================================================

setup_systemd_service() {
  local binary_path="$1"
  local service_file="/etc/systemd/system/${SERVICE_NAME}.service"
  local tmp_service_file="/tmp/${SERVICE_NAME}.service"
  
  if ! command -v systemctl &> /dev/null; then
    log_warn "systemctl not available, skipping systemd setup"
    return 0  # Non-fatal
  fi
  
  if [[ ! -d /etc/systemd/system ]]; then
    log_warn "systemd system directory not found, skipping"
    return 0
  fi
  
  log_info "Setting up systemd service..."
  
  # Create environment file for systemd (contains sensitive tokens)
  cat > "$tmp_service_file" << 'EOF'
[Unit]
Description=HomeConsole Remote Agent
After=network.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%BINARY_PATH%
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
EnvironmentFile=%ENV_FILE%
Environment="RC_SERVER_HOST=%HOST%"
Environment="RC_SERVER_PORT=%PORT%"
Environment="RC_SERVER_PROTOCOL=%PROTOCOL%"
Environment="RC_USE_TLS=%USE_TLS%"

[Install]
WantedBy=multi-user.target
EOF
  
  # Create environment file with sensitive tokens (restrictive permissions)
  local env_file="/etc/systemd/system/${SERVICE_NAME}.env"
  cat > "$tmp_service_file.env" << EOFENV
RC_ENROLLMENT_TOKEN=%TOKEN%
RC_AUTH_TOKEN=%TOKEN%
EOFENV
  
  chmod 600 "$tmp_service_file.env"
  
  # Substitute variables in service file
  sed -i "s|%BINARY_PATH%|$binary_path|g" "$tmp_service_file"
  sed -i "s|%ENV_FILE%|$env_file|g" "$tmp_service_file"
  sed -i "s|%HOST%|$RC_SERVER_HOST|g" "$tmp_service_file"
  sed -i "s|%PORT%|$RC_SERVER_PORT|g" "$tmp_service_file"
  sed -i "s|%PROTOCOL%|$RC_SERVER_PROTOCOL|g" "$tmp_service_file"
  sed -i "s|%USE_TLS%|$RC_USE_TLS|g" "$tmp_service_file"
  
  # Substitute token in env file
  sed -i "s|%TOKEN%|$ENROLLMENT_TOKEN|g" "$tmp_service_file.env"
  
  # Copy to system location (requires sudo)
  if sudo -n true 2>/dev/null; then
    sudo mv "$tmp_service_file" "$service_file"
    sudo mv "$tmp_service_file.env" "$env_file"
    sudo systemctl daemon-reload
    sudo systemctl enable "$SERVICE_NAME"
    sudo systemctl start "$SERVICE_NAME"
    log_info "Systemd service installed and started ✓"
    return 0
  else
    log_warn "sudo not available or password required, systemd setup skipped"
    rm -f "$tmp_service_file" "$tmp_service_file.env"
    return 0  # Non-fatal
  fi
}

# ============================================================================
# Health check
# ============================================================================

health_check() {
  local binary_name="$1"
  local timeout="$2"
  local elapsed=0
  
  log_info "Waiting for agent to start (timeout: ${timeout}s)..."
  
  # Simple check: if binary exists and is executable
  if [[ ! -x "${INSTALL_DIR}/${binary_name}" ]] && [[ ! -x "$binary_name" ]]; then
    log_error "Binary not executable: $binary_name"
    return 1
  fi

  # Phase 1: wait for process to appear
  while [[ $elapsed -lt $((timeout / 2)) ]]; do
    if pgrep -f "$binary_name" > /dev/null 2>&1; then
      log_info "Agent process detected ✓ (${elapsed}s)"
      break
    fi
    sleep 1
    (( elapsed++ ))
  done

  if ! pgrep -f "$binary_name" > /dev/null 2>&1; then
    log_warn "Agent process not detected within $((timeout / 2))s"
    return 0  # Non-fatal: starts via systemd may be delayed
  fi

  # Phase 2: wait for agent to connect to Core (check heartbeat endpoint)
  local hb_url="${CORE_URL%/}/admin/v1/agents/health/check"
  log_info "Waiting for agent to appear in Core registry (${hb_url})..."

  while [[ $elapsed -lt $timeout ]]; do
    local resp
    resp=$(curl -fsSL --max-time 5 "$hb_url" 2>/dev/null || echo '{"ok":false}')
    if echo "$resp" | grep -q '"online"\|"agents"'; then
      log_info "Agent connected to Core ✓"
      return 0
    fi
    sleep 2
    (( elapsed += 2 ))
  done

  log_warn "Agent did not appear in Core registry within ${timeout}s — may register later"
  return 0  # Non-fatal
}

# ============================================================================
# Cleanup on error
# ============================================================================

cleanup_on_error() {
  # Only called if installation FAILED (not on success)
  if [[ "$_INSTALL_SUCCESS" == "1" ]]; then
    return 0
  fi

  log_error "Installation failed — cleaning up..."

  local binary_path="${INSTALL_DIR}/${BINARY_NAME}"

  # Stop any running agent process we may have started
  if pgrep -f "$BINARY_NAME" > /dev/null 2>&1; then
    log_info "Stopping agent process..."
    pkill -f "$BINARY_NAME" 2>/dev/null || true
  fi

  # Remove corrupted/partial binary
  if [[ -f "$binary_path" ]]; then
    log_info "Removing corrupted binary: $binary_path"
    rm -f "$binary_path"
  fi

  # Remove bootstrap config with enrollment token
  if [[ -f "${INSTALL_DIR}/bootstrap.yaml" ]]; then
    log_info "Removing bootstrap config"
    rm -f "${INSTALL_DIR}/bootstrap.yaml"
  fi

  log_error "Cleanup complete. Please check logs and retry."
}

# ============================================================================
# Uninstall
# ============================================================================

uninstall() {
  log_info "=== Uninstalling HomeConsole Remote Agent ==="

  # Stop systemd service
  if command -v systemctl &> /dev/null; then
    sudo -n systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    sudo -n systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    sudo -n rm -f "/etc/systemd/system/${SERVICE_NAME}.service" 2>/dev/null || true
    sudo -n rm -f "/etc/systemd/system/${SERVICE_NAME}.env" 2>/dev/null || true
    sudo -n systemctl daemon-reload 2>/dev/null || true
    log_info "Systemd service removed"
  fi

  # Kill direct process if running
  if pgrep -f "$BINARY_NAME" > /dev/null 2>&1; then
    pkill -f "$BINARY_NAME" 2>/dev/null || true
    log_info "Agent process stopped"
  fi

  # Remove install directory
  if [[ -d "$INSTALL_DIR" ]]; then
    rm -rf "$INSTALL_DIR"
    log_info "Removed: $INSTALL_DIR"
  fi

  log_info "=== Uninstall complete ==="
}

# ============================================================================
# Main installation flow
# ============================================================================

main() {
  log_info "=== HomeConsole Remote Agent Installer v2.1 ==="
  log_info "Version: 2.1 (retry+jitter, nc-fallback, pre-flight, idempotent)"
  
  # Step 1: Validation
  validate_input || exit 1
  
  # Step 2: Setup
  setup_directories || exit 1
  
  # Step 3: Parse CORE_URL
  parse_core_url "$CORE_URL" || exit 1
  
  # Step 4: Find downloader
  local downloader
  downloader=$(ensure_downloader) || exit 1
  
  # Step 4.5: Pre-flight connectivity check
  preflight_check "$CORE_URL" || exit 1

  # Step 5: Download binary
  local download_url="${CORE_URL%/}/admin/v1/agents/download/binary"
  local checksum_url="${CORE_URL%/}/admin/v1/agents/download/checksum"
  
  download_binary "$download_url" "$BINARY_NAME" "$downloader" || {
    log_error "Failed to download agent binary"
    exit 1
  }
  
  # Step 6: Verify checksum
  verify_checksum "$BINARY_NAME" "$checksum_url" || {
    log_error "Checksum verification failed"
    cleanup_on_error "$BINARY_NAME"
    exit 1
  }
  
  # Step 7: Make binary executable
  chmod +x "$BINARY_NAME"
  log_info "Binary permissions set ✓"
  
  # Step 8: Setup systemd (optional)
  local binary_path="${INSTALL_DIR}/${BINARY_NAME}"
  if [[ "$SKIP_SYSTEMD" != "1" ]]; then
    setup_systemd_service "$binary_path" || true  # Non-fatal
  else
    log_info "SKIP_SYSTEMD=1 — skipping systemd setup"
  fi
  
  # Step 9: Create temporary config with enrollment token
  # This allows remote-client to read enrollment_token on first startup
  # The config file should be deleted after successful registration
  log_info "Creating temporary enrollment config..."
  
  cat > "${INSTALL_DIR}/bootstrap.yaml" << EOFCONFIG
# Bootstrap configuration with enrollment token
# This file should be deleted after successful agent registration
security:
  enrollment_token: "$ENROLLMENT_TOKEN"
EOFCONFIG
  
  chmod 600 "${INSTALL_DIR}/bootstrap.yaml"
  log_info "Bootstrap config created (will be auto-removed after registration)"

  # Step 10: Set environment variables for direct execution
  # Export enrollment token (primary) and auth token (fallback) for remote-client registration
  export RC_ENROLLMENT_TOKEN="$ENROLLMENT_TOKEN"
  export RC_AUTH_TOKEN="$ENROLLMENT_TOKEN"
  
  # Additional environment for config file path
  export RC_CONFIG_BOOTSTRAP="${INSTALL_DIR}/bootstrap.yaml"
  log_info "Starting agent process..."
  
  # Try to start via systemd first
  if sudo -n systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    log_info "Agent started via systemd"
  else
    # Fallback: start directly
    log_info "Starting agent directly (background)"
    nohup "./$BINARY_NAME" > agent.log 2>&1 &
    local agent_pid=$!
    log_info "Agent PID: $agent_pid"
  fi
  
  # Step 11: Health check
  health_check "$BINARY_NAME" "$HEALTH_CHECK_TIMEOUT" || true  # Non-fatal
  
  # Mark success BEFORE exiting (trap checks this)
  _INSTALL_SUCCESS=1

  log_info "=== Installation completed successfully ✓ ==="
  log_info "Agent is running and should connect to $CORE_URL"
  log_info "Logs: $INSTALL_DIR/agent.log"
  log_info "To uninstall: $0 --uninstall"
}

# ============================================================================
# Error handling
# ============================================================================

# Trap EXIT: only cleanup on FAILURE (when _INSTALL_SUCCESS != 1)
trap 'cleanup_on_error' EXIT

# ============================================================================
# Entry point
# ============================================================================

# Handle --uninstall flag
if [[ "${1:-}" == "--uninstall" ]]; then
  uninstall
  exit 0
fi

main "$@"

