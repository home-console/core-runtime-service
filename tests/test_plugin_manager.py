import pytest

from core.base_plugin import BasePlugin, PluginMetadata
from core.plugin_manager import PluginManager, PluginState


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


@pytest.mark.asyncio
async def test_load_start_stop_unload():
    pm = PluginManager()
    dp = DummyPlugin(None, name='p1')
    await pm.load_plugin(dp)
    assert pm.get_plugin_state('p1') == PluginState.LOADED

    await pm.start_plugin('p1')
    assert pm.get_plugin_state('p1') == PluginState.STARTED

    await pm.stop_plugin('p1')
    assert pm.get_plugin_state('p1') == PluginState.STOPPED

    await pm.unload_plugin('p1')
    assert pm.get_plugin_state('p1') == PluginState.UNLOADED


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
    assert set(pm.list_plugins()) == {'a', 'b'}


@pytest.mark.asyncio
async def test_load_error_sets_state():
    pm = PluginManager()
    bad = BadLoadPlugin(None, name='bad')
    with pytest.raises(RuntimeError):
        await pm.load_plugin(bad)
    assert pm.get_plugin_state('bad') == PluginState.ERROR
