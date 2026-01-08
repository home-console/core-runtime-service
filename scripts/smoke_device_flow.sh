#!/usr/bin/env bash
# Smoke test: device desired/reported/pending flow
# Requirements: bash, curl, jq

# Configurable params
BASE_URL="http://localhost:8000"
INTERNAL_ID="yandex-d43c7d12-cc9e-4790-95aa-565e0c47e1d8"
TIMEOUT=20
INTERVAL=1

# Desired value to set (true/false)
DESIRED_ON=true

# Helpers
die() {
  echo "[FAIL] $1" >&2
  if [[ -n "$LAST_STATE" ]]; then
    echo "--- last observed state (raw JSON) ---" >&2
    echo "$LAST_STATE" | jq . >&2 || echo "$LAST_STATE" >&2
    echo "-------------------------------------" >&2
  fi
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_cmd curl
require_cmd jq

echo "Smoke test: device flow for $INTERNAL_ID against $BASE_URL"

# Step 1: Read initial state
echo "[1] Read initial state"
RESP=$(curl -sS -w "\n%{http_code}" "$BASE_URL/admin/state/device.$INTERNAL_ID") || die "Failed to GET initial state"
HTTP=$(echo "$RESP" | tail -n1)
BODY=$(echo "$RESP" | sed '
$ d')
if [[ "$HTTP" != "200" ]]; then
  LAST_STATE="$BODY"
  die "GET returned HTTP $HTTP"
fi
LAST_STATE="$BODY"
# Validate structure
echo "$BODY" | jq -e '.desired, .reported, .pending' >/dev/null 2>&1 || die "State JSON missing required keys (desired/reported/pending)"
echo "Initial state:"
echo "$BODY" | jq .

# Step 2: Send command (set desired.on)
echo "[2] Send command: set desired.on = $DESIRED_ON"
CMD_PAYLOAD=$(jq -n --argjson on $DESIRED_ON '{state: {on: $on}}')
POST_RESP=$(curl -sS -w "\n%{http_code}" -X POST -H "Content-Type: application/json" -d "$CMD_PAYLOAD" "$BASE_URL/admin/v1/devices/$INTERNAL_ID/state") || die "Failed to POST command"
POST_HTTP=$(echo "$POST_RESP" | tail -n1)
POST_BODY=$(echo "$POST_RESP" | sed '
$ d')
if [[ "$POST_HTTP" != "200" ]]; then
  echo "POST response body:" >&2
  echo "$POST_BODY" | jq . >&2 || echo "$POST_BODY" >&2
  die "POST returned HTTP $POST_HTTP"
fi
# Quick check response contains queued: true
echo "$POST_BODY" | jq -e '.ok == true and .queued == true' >/dev/null 2>&1 || die "POST did not return ok/queued"
echo "POST accepted:"
echo "$POST_BODY" | jq .

# Step 3: Verify pending == true
echo "[3] Verify pending == true"
RESP2=$(curl -sS -w "\n%{http_code}" "$BASE_URL/admin/state/device.$INTERNAL_ID") || die "Failed to GET state after POST"
HTTP2=$(echo "$RESP2" | tail -n1)
BODY2=$(echo "$RESP2" | sed '
$ d')
if [[ "$HTTP2" != "200" ]]; then
  LAST_STATE="$BODY2"
  die "GET (after POST) returned HTTP $HTTP2"
fi
LAST_STATE="$BODY2"
PENDING_VAL=$(echo "$BODY2" | jq -r '.pending')
if [[ "$PENDING_VAL" != "true" ]]; then
  echo "State after POST:" | jq -n '$ARGS.positional' --args "$BODY2" >/dev/null 2>&1 || true
  die "pending is not true after POST (pending=$PENDING_VAL)"
fi
echo "pending == true as expected"

# Step 4: Poll until reported matches desired and pending == false
echo "[4] Poll until reported matches desired ($TIMEOUT s timeout)"
START_TS=$(date +%s)
END_TS=$((START_TS + TIMEOUT))
SUCCESS=0
while [[ $(date +%s) -le $END_TS ]]; do
  S=$(curl -sS -f "$BASE_URL/admin/state/device.$INTERNAL_ID") || true
  if [[ -z "$S" ]]; then
    sleep $INTERVAL
    continue
  fi
  LAST_STATE="$S"
  # reported.on and pending
  REPORTED_ON=$(echo "$S" | jq -r '.reported.on // empty')
  PENDING=$(echo "$S" | jq -r '.pending // empty')
  # Normalize booleans to "true"/"false"
  if [[ "$REPORTED_ON" == "true" || "$REPORTED_ON" == "false" ]]; then
    :
  elif [[ "$REPORTED_ON" == "" ]]; then
    REPORTED_ON=""
  fi
  if [[ "$PENDING" == "false" && "$REPORTED_ON" == "$DESIRED_ON" ]]; then
    SUCCESS=1
    break
  fi
  sleep $INTERVAL
done

if [[ $SUCCESS -eq 1 ]]; then
  echo "[OK] reported matches desired and pending=false"
  echo "Final state:"
  echo "$LAST_STATE" | jq .
  exit 0
else
  die "Timeout waiting for reported==desired and pending=false"
fi
