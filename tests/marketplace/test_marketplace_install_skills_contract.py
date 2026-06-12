"""
Contract: publish (marketplace-api) → install from registry (core) → skills visible (core).

Full cross-service CI is not wired in the monorepo yet; the pipeline is covered in three tests:

1. ``marketplace-api/tests/test_skills_publish_pipeline.py`` — signed release with ``skills`` in manifest
2. ``tests/marketplace/test_marketplace_install_from_registry_e2e.py`` — HTTPS registry → install → plugin load
3. ``tests/skills/test_skills_e2e_pipeline.py`` — on-disk plugin → SkillsModule list/get

This file ties (2) + (3): after ``marketplace.install_from_registry``, ``SkillsModule`` rehydrates
skills from the extracted ``plugin.json``.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.operations.models import Operation, OperationInitiator, OperationInitiatorKind
from modules.marketplace.services import MarketplaceService
from modules.skills.module import SkillsModule
from tests.conftest import InMemoryStorageAdapter
from tests.marketplace.test_marketplace_install_from_registry_e2e import (
    _MemStorage,
    _MinimalRuntime,
    _RecordingPluginManager,
    _make_self_signed_tls_context,
    _sha256_file,
    _sign_registry_zip,
)

import aiohttp.web


PLUGIN_NAME = "e2e_skills_plugin"
SKILL_ID = f"{PLUGIN_NAME}.ping"


def _build_skills_plugin_zip(out_zip: Path) -> None:
    plugin_json = {
        "name": PLUGIN_NAME,
        "version": "1.0.0",
        "description": "e2e skills registry",
        "author": "test",
        "class_path": "plugin.E2EPlugin",
        "skills": [
            {
                "name": "ping",
                "intent": "health check",
                "service": f"{PLUGIN_NAME}.skill.ping",
            }
        ],
    }
    plugin_py = """
from core.kernel.base_plugin import BasePlugin, PluginMetadata

class E2EPlugin(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="e2e_skills_plugin",
            version="1.0.0",
            description="e2e skills registry",
            author="test",
        )
""".lstrip()

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "plugin.json").write_text(json.dumps(plugin_json), encoding="utf-8")
        (root / "plugin.py").write_text(plugin_py, encoding="utf-8")
        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(root / "plugin.json", arcname="plugin.json")
            zf.write(root / "plugin.py", arcname="plugin.py")


@pytest.mark.asyncio
async def test_registry_install_then_skills_rehydrate_from_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Install skills manifest from mock registry; SkillsModule lists skill from plugins_dir."""
    monkeypatch.setenv("MARKETPLACE_ALLOW_LOCALHOST", "true")

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    zip_path = tmp_path / f"{PLUGIN_NAME}.zip"
    _build_skills_plugin_zip(zip_path)
    sha, sig_b64, pub_b64 = _sign_registry_zip(zip_path)

    ssl_ctx = _make_self_signed_tls_context(tmp_path)
    app = aiohttp.web.Application()
    ZIP_PATH_KEY = aiohttp.web.AppKey("zip_path", Path)
    SHA256_KEY = aiohttp.web.AppKey("sha256", str)
    SIG_KEY = aiohttp.web.AppKey("sig_b64", str)
    PUB_KEY = aiohttp.web.AppKey("pub_b64", str)
    app[ZIP_PATH_KEY] = zip_path
    app[SHA256_KEY] = sha
    app[SIG_KEY] = sig_b64
    app[PUB_KEY] = pub_b64

    async def registry_index(request: aiohttp.web.Request) -> aiohttp.web.Response:
        base = f"{request.url.scheme}://{request.host}"
        payload = {
            "registry_version": 1,
            "updated_at": "2026-01-01T00:00:00Z",
            "plugins": {
                PLUGIN_NAME: {
                    "channels": {
                        "stable": {
                            "version": "1.0.0",
                            "url": f"{base}/{PLUGIN_NAME}.zip",
                            "sha256": request.app[SHA256_KEY],
                            "signature": request.app[SIG_KEY],
                            "public_key": request.app[PUB_KEY],
                        }
                    },
                    "versions": {},
                }
            },
        }
        return aiohttp.web.json_response(payload)

    async def plugin_zip(request: aiohttp.web.Request) -> aiohttp.web.FileResponse:
        return aiohttp.web.FileResponse(path=request.app[ZIP_PATH_KEY])

    app.router.add_get("/registry/index.json", registry_index)
    app.router.add_get(f"/{PLUGIN_NAME}.zip", plugin_zip)

    _orig_client_session = aiohttp.ClientSession

    def _insecure_client_session(*args, **kwargs):
        kwargs.setdefault("connector", aiohttp.TCPConnector(ssl=False))
        return _orig_client_session(*args, **kwargs)

    import modules.marketplace.registry_client as registry_client_mod
    import modules.marketplace.installer as installer_mod

    monkeypatch.setattr(registry_client_mod, "aiohttp", aiohttp, raising=False)
    monkeypatch.setattr(installer_mod, "aiohttp", aiohttp, raising=False)
    monkeypatch.setattr(aiohttp, "ClientSession", _insecure_client_session)

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, host="127.0.0.1", port=0, ssl_context=ssl_ctx)
    await site.start()

    try:
        port = int(site._server.sockets[0].getsockname()[1])  # type: ignore[union-attr]
        storage = _MemStorage()
        pm = _RecordingPluginManager()
        runtime = _MinimalRuntime(storage=storage, plugin_manager=pm, plugins_dir=plugins_dir)

        svc = MarketplaceService(runtime)
        op = Operation(
            operation_id="op-skills-contract",
            op_type="marketplace.install_from_registry",
            params={
                "plugin_name": PLUGIN_NAME,
                "registry_url": f"https://127.0.0.1:{port}/registry/index.json",
                "channel": "stable",
            },
            initiator=OperationInitiator(kind=OperationInitiatorKind.ADMIN),
        )
        result = await svc.handle_install_from_registry(op)
        assert result["status"] == "success"
        assert (plugins_dir / PLUGIN_NAME / "plugin.json").is_file()

        skills_runtime = SimpleNamespace(
            storage=InMemoryStorageAdapter(),
            _config=SimpleNamespace(plugins_dir=str(plugins_dir)),
            event_bus=None,
        )
        mod = SkillsModule(skills_runtime)
        mod.context = SimpleNamespace(
            services=SimpleNamespace(register=AsyncMock(), unregister=AsyncMock()),
            http=MagicMock(),
        )
        await mod.register()
        await mod.start()

        listed = await mod._service_list()
        assert listed["total"] >= 1
        ids = [item["id"] for item in listed["items"]]
        assert SKILL_ID in ids
        got = await mod._service_get(SKILL_ID)
        assert got["plugin_name"] == PLUGIN_NAME
        assert got["name"] == "ping"
        await mod.stop()
    finally:
        await runner.cleanup()
