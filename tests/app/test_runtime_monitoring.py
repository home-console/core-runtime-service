"""Runtime health collector — plugin auto-load errors."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.runtime_monitoring import HealthStatus, collect_runtime_health
from core.kernel.plugin_registry import PluginState


@pytest.mark.asyncio
async def test_health_degraded_when_plugin_load_errors_present():
    runtime = MagicMock()
    runtime._start_time = 1.0
    runtime.plugin_load_errors = {"broken_plugin": "import failed"}
    runtime.storage.get = AsyncMock(return_value={"ok": True})
    runtime.module_manager.list_modules.return_value = ["api"]
    runtime.module_manager.get_required_modules.return_value = ["api"]
    runtime.plugin_manager.list_plugins = AsyncMock(return_value=[])
    runtime.plugin_manager.get_plugin_state = AsyncMock(return_value=PluginState.STARTED)

    snapshot = await collect_runtime_health(runtime)

    assert snapshot["status"] == HealthStatus.DEGRADED.value
    assert snapshot["checks"]["plugin_auto_load"] == HealthStatus.DEGRADED.value
    assert snapshot["checks"]["plugin_load_errors"] == {
        "broken_plugin": "import failed"
    }
