from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from core.exceptions import ForbiddenError
from core.kernel.plugin_loader import PluginManifestLoader


@pytest.mark.asyncio
async def test_plugin_loader_does_not_pass_raw_runtime_into_init(tmp_path: Path) -> None:
    (tmp_path / "plugins").mkdir()
    plugin_dir = tmp_path / "plugins" / "evil"
    plugin_dir.mkdir(parents=True)

    # Plugin tries to bypass allowlist in __init__ by calling a disallowed service.
    (plugin_dir / "plugin.py").write_text(
        "from sdk.plugin import BasePlugin\n"
        "\n"
        "class EvilPlugin(BasePlugin):\n"
        "    def __init__(self, runtime):\n"
        "        super().__init__(runtime)\n"
        "        # If raw runtime leaks here, this could call any service.\n"
        "        # Loader must pass a proxied runtime facade instead.\n"
        "        self._init_call = runtime.service_registry.call\n"
        "\n"
        "    @property\n"
        "    def metadata(self):\n"
        "        from sdk.plugin import PluginMetadata\n"
        "        return PluginMetadata(name='evil', version='0.0.1')\n",
        encoding="utf-8",
    )

    manifest: Dict[str, Any] = {
        "name": "evil",
        "version": "0.0.1",
        "description": "init surface test",
        "author": "test",
        "class_path": "plugin.EvilPlugin",
        "allowed_services": ["logger.log"],
    }

    class _SR:
        async def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
            return {"ok": True}

        async def has_service(self, name: str) -> bool:
            return True

    runtime = SimpleNamespace(
        storage=SimpleNamespace(),  # storage isn't used in this test
        service_registry=_SR(),
        http=None,
        operations=None,
        state=None,
        event_bus=None,
        capability_registry={},
        plugin_default_allowed_services=["logger.log"],
    )

    captured = {}

    async def _load_plugin(plugin_obj: Any) -> None:
        captured["plugin"] = plugin_obj

    async def _noop_logger(*_a: Any, **_k: Any) -> None:
        return None

    ok = await PluginManifestLoader.load_plugin_from_manifest(
        manifest=manifest,
        plugin_dir=plugin_dir,
        runtime=runtime,
        load_plugin_func=_load_plugin,
        logger_func=_noop_logger,
    )
    assert ok is True

    plugin = captured["plugin"]
    # Disallowed service must be blocked even from surfaces captured in __init__.
    with pytest.raises(ForbiddenError):
        await plugin._init_call("disallowed.service")

