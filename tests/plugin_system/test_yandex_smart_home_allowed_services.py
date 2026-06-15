import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from core.kernel.base_plugin import BasePlugin, PluginMetadata
from core.kernel.plugin_contract import PluginContext, PluginManifest
from core.kernel.plugin_sandbox import PluginSandbox
from core.runtime.runtime_context import RuntimeContext
from modules.plugins.isolation import ServiceProxy, StorageProxy


class _YandexSmartHomePluginStub(BasePlugin):
    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(name="yandex_smart_home", version="0.1.0")


@pytest.mark.asyncio
async def test_yandex_smart_home_can_call_auto_map_own_but_not_auto_map_external():
    manifest_path = (
        Path(__file__).resolve().parents[2] / "plugins" / "yandex_smart_home" / "plugin.json"
    )
    manifest_data = json.loads(manifest_path.read_text())

    mock_runtime = Mock()
    mock_storage = Mock()
    mock_service_registry = Mock()

    mock_runtime.storage = mock_storage
    mock_runtime.service_registry = mock_service_registry
    mock_runtime.plugin_storage_proxy_cls = StorageProxy
    mock_runtime.plugin_service_proxy_cls = ServiceProxy
    mock_runtime.plugin_default_allowed_services = ["logger.log"]
    mock_runtime.http = Mock()
    mock_runtime.operations = Mock()
    mock_runtime.capability_registry = Mock()
    mock_runtime.create_context = Mock(
        return_value=RuntimeContext(
            storage=mock_storage,
            services=mock_service_registry,
            http=mock_runtime.http,
            capabilities=mock_runtime.capability_registry,
            operations=mock_runtime.operations,
        )
    )

    mock_service_registry.call = AsyncMock(return_value={"ok": True})
    mock_service_registry.has = AsyncMock(return_value=True)

    plugin = _YandexSmartHomePluginStub(mock_runtime)
    manifest = PluginManifest.from_dict(manifest_data)
    ctx = PluginContext.create(plugin, manifest)
    object.__setattr__(plugin, "_plugin_context", ctx)

    PluginSandbox.create_isolation_context(plugin, mock_runtime, "yandex_smart_home")

    # Self-service auto-mapping for the plugin's own provider — allowed.
    out = await plugin.services.call("devices.auto_map_own", provider="acme")
    assert out == {"ok": True}

    # Logging stays allowed (was previously covered by the default allowlist).
    out = await plugin.services.call("logger.warning", message="test")
    assert out == {"ok": True}

    # The admin-only variant must remain off-limits to plugins.
    from core.exceptions import ForbiddenError

    with pytest.raises(ForbiddenError):
        await plugin.services.call("devices.auto_map_external", provider="acme")
