import pytest

from core.kernel.plugin_metadata_storage_contract import (
    PLUGIN_METADATA_NAMESPACE,
    PLUGIN_METADATA_SCHEMA_VERSION,
    PluginMetadataRecord,
)
from core.kernel.plugin_storage_manager import PluginStorageManager


class _MemStorage:
    def __init__(self):
        self.data = {}

    async def set(self, namespace, key, value):
        self.data[(namespace, key)] = value

    async def get(self, namespace, key):
        return self.data.get((namespace, key))

    async def list_keys(self, namespace):
        return [k for (ns, k) in self.data.keys() if ns == namespace]


class _Runtime:
    def __init__(self, storage):
        self.storage = storage


@pytest.mark.asyncio
async def test_plugin_storage_manager_writes_schema_version_and_normalizes_fields():
    storage = _MemStorage()
    mgr = PluginStorageManager(_Runtime(storage))

    class _Meta:
        name = "p"
        version = "1.2.3"
        class_path = "plugins.p.plugin.P"
        execution_mode = "in_process"
        container_config = None
        capabilities_provided = ["a", 1]
        capabilities_required = None
        dependencies = ("x", "y")

    await mgr.save_plugin_metadata("p", _Meta())
    raw = await storage.get(PLUGIN_METADATA_NAMESPACE, "p")
    assert isinstance(raw, dict)
    assert raw["schema_version"] == PLUGIN_METADATA_SCHEMA_VERSION
    assert raw["name"] == "p"
    assert raw["capabilities_provided"] == ["a", "1"]
    assert raw["capabilities_required"] == []
    assert raw["dependencies"] == ["x", "y"]


@pytest.mark.asyncio
async def test_plugin_storage_manager_normalizes_legacy_dict_without_schema_version_on_read():
    storage = _MemStorage()
    storage.data[(PLUGIN_METADATA_NAMESPACE, "p")] = {
        "name": "p",
        "version": "0.1.0",
        "loaded": True,
        "capabilities_provided": ["a"],
    }
    mgr = PluginStorageManager(_Runtime(storage))
    value = await mgr.get_plugin_metadata("p")
    assert value is not None
    assert value["schema_version"] == PLUGIN_METADATA_SCHEMA_VERSION
    assert value["execution_mode"] == "in_process"


@pytest.mark.asyncio
async def test_plugin_storage_manager_mark_unloaded_updates_loaded_flag():
    storage = _MemStorage()
    mgr = PluginStorageManager(_Runtime(storage))

    class _Meta:
        name = "p"

    await mgr.save_plugin_metadata("p", _Meta())
    await mgr.mark_plugin_unloaded("p")
    value = await mgr.get_plugin_metadata("p")
    assert value is not None
    assert value["loaded"] is False
    assert value["unloaded_at"] is not None

