#!/usr/bin/env bash
# Start dev stage with frontend + core-runtime behind Caddy.
#
# Порты по умолчанию не пересекаются с prod (edge на 80/443):
#   UI (Caddy)  → http://localhost:${DEV_HTTP_PORT:-18080}
#   Ядро (API) → http://localhost:${DEV_CORE_PORT:-18000}
#
# Usage:
#   ./deploy/dev/start.sh              # with frontend
#   ./deploy/dev/start.sh --no-ui      # core-runtime only
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

DEV_HTTP_PORT="${DEV_HTTP_PORT:-18080}"
DEV_CORE_PORT="${DEV_CORE_PORT:-18000}"

cd "$SCRIPT_DIR"

if [[ "${1:-}" == "--no-ui" ]]; then
    echo "▶ Starting core-runtime only (http://localhost:${DEV_CORE_PORT})"
    docker compose -f docker-compose.yml up -d core-runtime
    echo "✓ core-runtime running on http://localhost:${DEV_CORE_PORT}"
    exit 0
fi

# Check frontend exists
if [[ ! -f "$FRONTEND_DIR/index.html" ]]; then
    echo "⚠ Frontend not found at $FRONTEND_DIR"
    echo ""
    echo "Build frontend first:"
    echo "  cd $PROJECT_ROOT/../platform-home-console"
    echo "  pnpm install"
    echo "  pnpm build:web"
    echo "  cp -r apps/web/dist $FRONTEND_DIR"
    echo ""
    echo "Or start without UI:"
    echo "  $0 --no-ui"
    exit 1
fi

echo "▶ Starting dev stage (http://localhost:${DEV_HTTP_PORT} — параллельно с prod на :80)"
docker compose -f docker-compose.yml up -d
echo ""
echo "✓ Services running:"
echo "  Frontend (Caddy): http://localhost:${DEV_HTTP_PORT}"
echo "  API (через Caddy): http://localhost:${DEV_HTTP_PORT}/api/v1/..."
echo "  Admin:            http://localhost:${DEV_HTTP_PORT}/api/v1/admin/..."
echo "  Auth:             http://localhost:${DEV_HTTP_PORT}/api/v1/auth/..."
echo "  Core (direct):    http://localhost:${DEV_CORE_PORT}"
