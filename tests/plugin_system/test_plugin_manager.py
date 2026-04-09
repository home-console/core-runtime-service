import pytest

from core.kernel.base_plugin import BasePlugin, PluginMetadata
from core.kernel.plugin_manager import PluginManager
from core.kernel.plugin_registry import PluginState


class DummyPlugin(BasePlugin):
    def __init__(self, runtime, name='dummy', deps=None):
        super().__init__(runtime)
        self._meta = PluginMetadata(name=name, version='0.1', dependencies=(deps or []))
        self.loaded = False
        self.started = False

    @property
    def metadata(self):
        return self._meta

    async def on_load(self):
        self.loaded = True
        await super().on_load()

    async def on_start(self):
        self.started = True
        await super().on_start()

    async def on_stop(self):
        self.started = False
        await super().on_stop()


class BadLoadPlugin(DummyPlugin):
    async def on_load(self):
        raise RuntimeError('bad')


class BadStartPlugin(DummyPlugin):
    async def on_start(self):
        raise RuntimeError('start failed')


@pytest.mark.asyncio
async def test_load_start_stop_unload():
    pm = PluginManager()
    dp = DummyPlugin(None, name='p1')
    await pm.load_plugin(dp)
    assert await pm.get_plugin_state('p1') == PluginState.LOADED

    await pm.start_plugin('p1')
    assert await pm.get_plugin_state('p1') == PluginState.STARTED

    await pm.stop_plugin('p1')
    assert await pm.get_plugin_state('p1') == PluginState.STOPPED

    await pm.unload_plugin('p1')
    assert await pm.get_plugin_state('p1') == PluginState.UNLOADED


@pytest.mark.asyncio
async def test_dependency_check():
    pm = PluginManager()
    p_a = DummyPlugin(None, name='a')
    p_b = DummyPlugin(None, name='b', deps=['a'])

    # loading b before a should fail
    with pytest.raises(ValueError):
        await pm.load_plugin(p_b)

    await pm.load_plugin(p_a)
    await pm.load_plugin(p_b)
    assert set(await pm.list_plugins()) == {'a', 'b'}


@pytest.mark.asyncio
async def test_load_error_sets_state():
    pm = PluginManager()
    bad = BadLoadPlugin(None, name='bad')
    with pytest.raises(RuntimeError):
        await pm.load_plugin(bad)
    assert await pm.get_plugin_state('bad') == PluginState.ERROR


@pytest.mark.asyncio
async def test_start_plugin_autostarts_dependency():
    pm = PluginManager()

    dep = DummyPlugin(None, name='dep')
    child = DummyPlugin(None, name='child', deps=['dep'])

    await pm.load_plugin(dep)
    await pm.load_plugin(child)

    # child start should auto-start dep first
    await pm.start_plugin('child')

    assert dep.started is True
    assert child.started is True
    assert await pm.get_plugin_state('dep') == PluginState.STARTED
    assert await pm.get_plugin_state('child') == PluginState.STARTED


@pytest.mark.asyncio
async def test_start_plugin_blocked_when_dependency_not_ready():
    pm = PluginManager()

    dep = BadStartPlugin(None, name='dep')
    child = DummyPlugin(None, name='child', deps=['dep'])

    await pm.load_plugin(dep)
    await pm.load_plugin(child)

    # child should not raise; it should remain blocked in LOADED state
    await pm.start_plugin('child')

    assert await pm.get_plugin_state('child') == PluginState.LOADED
    reason = await pm.get_plugin_block_reason('child')
    assert isinstance(reason, dict)
    assert 'dependency_not_ready' in reason
    assert reason['dependency_not_ready'][0]['dependency'] == 'dep'


