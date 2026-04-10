#!/usr/bin/env bash
# Start dev stage with frontend + core-runtime behind Caddy.
#
# Usage:
#   ./deploy/dev/start.sh              # with frontend
#   ./deploy/dev/start.sh --no-ui      # core-runtime only (port 8000)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

cd "$SCRIPT_DIR"

if [[ "${1:-}" == "--no-ui" ]]; then
    echo "▶ Starting core-runtime only (http://localhost:8000)"
    docker compose -f docker-compose.yml up -d core-runtime
    echo "✓ core-runtime running on http://localhost:8000"
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

echo "▶ Starting dev stage (http://localhost)"
docker compose -f docker-compose.yml up -d
echo ""
echo "✓ Services running:"
echo "  Frontend:  http://localhost"
echo "  API:       http://localhost/api/v1/..."
echo "  Admin:     http://localhost/admin/v1/..."
echo "  Auth:      http://localhost/auth/v1/..."
echo "  Core (direct): http://localhost:8000"
