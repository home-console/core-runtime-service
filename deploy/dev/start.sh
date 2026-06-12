#!/usr/bin/env bash
# Start a local demo stack: platform UI + core-runtime behind Caddy.
#
# Usage:
#   ./deploy/dev/start.sh
#   ./deploy/dev/start.sh --no-ui
#   ./deploy/dev/start.sh --skip-build
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CORE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="$(cd "$CORE_ROOT/.." && pwd)"
PLATFORM_ROOT="$REPO_ROOT/platform-home-console"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
DIST_DIR="$PLATFORM_ROOT/apps/web/dist"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yml"

DEV_HTTP_PORT="${DEV_HTTP_PORT:-18080}"
DEV_CORE_PORT="${DEV_CORE_PORT:-18000}"
NO_UI=0
SKIP_BUILD=0

for arg in "$@"; do
    case "$arg" in
        --no-ui)
            NO_UI=1
            ;;
        --skip-build)
            SKIP_BUILD=1
            ;;
        *)
            echo "Unknown argument: $arg" >&2
            echo "Usage: $0 [--no-ui] [--skip-build]" >&2
            exit 2
            ;;
    esac
done

ensure_core_env() {
    if [[ -f "$CORE_ROOT/.env" ]]; then
        return
    fi
    if [[ ! -f "$CORE_ROOT/.env.example" ]]; then
        echo "Missing $CORE_ROOT/.env.example" >&2
        exit 1
    fi
    cp "$CORE_ROOT/.env.example" "$CORE_ROOT/.env"
    local key
    key="$(openssl rand -hex 32)"
    perl -0pi -e "s/^RUNTIME_MASTER_KEY=.*$/RUNTIME_MASTER_KEY=$key/m" "$CORE_ROOT/.env"
    echo "Created $CORE_ROOT/.env with a fresh RUNTIME_MASTER_KEY"
}

build_frontend() {
    if [[ ! -d "$PLATFORM_ROOT" ]]; then
        echo "platform-home-console not found at $PLATFORM_ROOT" >&2
        exit 1
    fi
    if ! command -v pnpm >/dev/null 2>&1; then
        echo "pnpm is required to build the platform demo" >&2
        exit 1
    fi

    echo "Building platform web bundle"
    (
        cd "$PLATFORM_ROOT"
        pnpm build:web
    )

    if [[ ! -f "$DIST_DIR/index.html" ]]; then
        echo "Frontend build did not produce $DIST_DIR/index.html" >&2
        exit 1
    fi

    mkdir -p "$FRONTEND_DIR"
    find "$FRONTEND_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    cp -R "$DIST_DIR"/. "$FRONTEND_DIR/"
}

cd "$SCRIPT_DIR"
ensure_core_env

if [[ "$NO_UI" -eq 1 ]]; then
    echo "Starting core-runtime only on http://localhost:${DEV_CORE_PORT}"
    docker compose -f "$COMPOSE_FILE" up -d core-runtime
    echo "Core runtime is available at http://localhost:${DEV_CORE_PORT}"
    exit 0
fi

if [[ "$SKIP_BUILD" -eq 0 ]]; then
    build_frontend
elif [[ ! -f "$FRONTEND_DIR/index.html" ]]; then
    echo "Frontend assets are missing in $FRONTEND_DIR. Run without --skip-build first." >&2
    exit 1
fi

echo "Starting platform + core demo on http://localhost:${DEV_HTTP_PORT}"
docker compose -f "$COMPOSE_FILE" up -d
echo ""
echo "Demo is running:"
echo "  UI:              http://localhost:${DEV_HTTP_PORT}"
echo "  API via Caddy:   http://localhost:${DEV_HTTP_PORT}/api/v1/..."
echo "  Admin via Caddy: http://localhost:${DEV_HTTP_PORT}/api/v1/admin/..."
echo "  Core direct:     http://localhost:${DEV_CORE_PORT}"
