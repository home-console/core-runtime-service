#!/usr/bin/env python3
"""
Export FastAPI OpenAPI schema to openapi.json.

Usage:
    python scripts/export_openapi.py [--out openapi.json] [--profile <profile>]

The script starts a minimal runtime, binds all routes, then dumps the schema.
It does NOT start plugins — only the core modules register their endpoints.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Run from project root so imports work
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

# Load .env if present
try:
    from app.env_bootstrap import load_dotenv
    load_dotenv()
except Exception:
    pass


async def _build_schema(profile_name: str | None = None) -> dict:
    """Build runtime, register all modules, bind routes, extract OpenAPI schema."""
    from fastapi import FastAPI
    from app.bootstrap import build_runtime, resolve_module_specs_for_profile
    from core.runtime.config import Config
    from modules.api.route_binding import bind_routes
    from modules.storage.factory import build_storage_stack
    from core.runtime.state_engine import StateEngine

    config = Config()
    config.db_path = os.getenv("STORAGE_PATH", str(PROJECT_ROOT / "data" / "schema_export.db"))

    state_engine = StateEngine()
    storage_stack = await build_storage_stack(config, state_engine)

    module_specs = resolve_module_specs_for_profile(profile_name, config)

    runtime = await build_runtime(
        storage_port=storage_stack.core_port,
        config=config,
        vault_port=storage_stack.vault_port,
        state_engine=state_engine,
        storage_manager=storage_stack.manager,
        module_specs=module_specs,
    )

    app = FastAPI(
        title="Home Console API",
        version="0.1.0",
        description="Home Console Core Runtime API",
    )
    bind_routes(runtime, app)

    schema = app.openapi()
    await storage_stack.manager.close()
    return schema


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Export OpenAPI schema")
    parser.add_argument("--out", default="openapi.json", help="Output file path")
    parser.add_argument("--profile", default=None, help="Runtime profile name")
    args = parser.parse_args()

    schema = asyncio.run(_build_schema(args.profile))

    out_path = Path(args.out)
    out_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False))
    print(f"OpenAPI schema written to {out_path} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
