import pytest

from core.exceptions import ForbiddenError
from core.kernel.base_plugin import BasePlugin
from core.kernel.plugin_contract import PluginContext, PluginManifest
from core.kernel.plugin_sandbox import PluginSandbox
from modules.plugins.isolation import ServiceProxy, StorageProxy

from unittest.mock import AsyncMock, Mock


class PluginForAllowedServices(BasePlugin):
    @property
    def metadata(self):
        # Metadata is irrelevant for this test; required by BasePlugin interface.
        from core.kernel.base_plugin import PluginMetadata

        return PluginMetadata(name="test_plugin", version="1.0.0")


@pytest.mark.asyncio
async def test_plugin_services_proxy_uses_manifest_allowed_services():
    # Arrange runtime with required proxy classes
    mock_runtime = Mock()
    mock_storage = Mock()
    mock_service_registry = Mock()

    mock_runtime.storage = mock_storage
    mock_runtime.service_registry = mock_service_registry
    mock_runtime.plugin_storage_proxy_cls = StorageProxy
    mock_runtime.plugin_service_proxy_cls = ServiceProxy
    mock_runtime.plugin_default_allowed_services = ["logger.log"]

    # ServiceProxy will call: service_registry.call(service_name, **kwargs)
    mock_service_registry.call = AsyncMock(return_value={"ok": True})
    mock_service_registry.has = AsyncMock(return_value=True)

    plugin = PluginForAllowedServices(None)
    manifest = PluginManifest.from_dict(
        {
            "name": "test_plugin",
            "version": "1.0.0",
            "class_path": "unused",
            "allowed_services": ["allowed.service"],
        }
    )
    ctx = PluginContext.create(plugin, manifest)
    object.__setattr__(plugin, "_plugin_context", ctx)

    # Act
    PluginSandbox.create_isolation_context(plugin, mock_runtime, "test_plugin")

    # Assert: disallowed service must be blocked
    with pytest.raises(ForbiddenError):
        await plugin.services.call("disallowed.service", x=1)

    # Assert: allowed service passes through to registry.call
    out = await plugin.services.call("allowed.service", x=1)
    assert out == {"ok": True}
    mock_service_registry.call.assert_awaited()

