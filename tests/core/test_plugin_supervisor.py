import asyncio

import pytest

from core.kernel.plugin_supervisor import PluginStatus, PluginSupervisor


@pytest.mark.asyncio
async def test_supervisor_isolates_crashing_plugin():
    """Падение одного плагина не влияет на другие."""
    supervisor = PluginSupervisor()
    crashed: list[str] = []

    async def on_failed(name: str, exc: Exception) -> None:
        crashed.append(name)

    supervisor.on_plugin_failed(on_failed)

    async def good_plugin():
        await asyncio.sleep(10)  # долгоживущий

    async def bad_plugin():
        raise RuntimeError("intentional crash")

    handle_good = await supervisor.spawn("good", good_plugin)
    handle_bad = await supervisor.spawn("bad", bad_plugin)

    await asyncio.sleep(0.1)  # дать bad упасть

    assert handle_bad.status == PluginStatus.DEGRADED
    assert handle_good.status == PluginStatus.RUNNING
    assert "bad" in crashed

    await supervisor.stop_all(timeout=1.0)


@pytest.mark.asyncio
async def test_supervisor_cancelled_error_propagates():
    """CancelledError не перехватывается supervisor (задача отменяется)."""
    supervisor = PluginSupervisor()

    async def cancellable():
        await asyncio.sleep(100)

    handle = await supervisor.spawn("cancellable", cancellable)
    await supervisor.stop_plugin("cancellable")
    assert handle.status == PluginStatus.STOPPED


@pytest.mark.asyncio
async def test_stop_all_graceful():
    """stop_all() корректно завершает все плагины."""
    supervisor = PluginSupervisor()
    for i in range(5):
        await supervisor.spawn(f"plugin_{i}", lambda: asyncio.sleep(100))
    await supervisor.stop_all(timeout=2.0)
    statuses = supervisor.list_plugins()
    assert all(s == PluginStatus.STOPPED for s in statuses.values())

