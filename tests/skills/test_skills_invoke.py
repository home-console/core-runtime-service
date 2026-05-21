from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.kernel.plugin_registry import PluginState
from modules.skills.module import SkillsModule
from modules.skills.registry import SkillRegistry


class _Registry:
    def __init__(self, services: dict[str, object]) -> None:
        self._services = services
        self.calls: list[tuple[str, dict]] = []

    async def has_service(self, name: str) -> bool:
        return name in self._services

    async def call(self, name: str, **kwargs):
        self.calls.append((name, kwargs))
        handler = self._services[name]
        out = handler(**kwargs)
        if hasattr(out, "__await__"):
            return await out
        return out


@pytest.mark.asyncio
async def test_invoke_uses_explicit_service():
    reg = SkillRegistry()
    reg.register_plugin_skills(
        "demo",
        "1.0.0",
        [{"name": "snap", "intent": "snap", "service": "demo.custom.handler"}],
    )
    runtime = SimpleNamespace(
        service_registry=_Registry({"demo.custom.handler": lambda **kw: {"x": kw.get("n")}})
    )
    mod = SkillsModule(runtime)
    mod.registry = reg
    out = await mod._service_invoke("demo.snap", params={"n": 7})
    assert out["ok"] is True
    assert out["service"] == "demo.custom.handler"
    assert out["result"] == {"x": 7}


@pytest.mark.asyncio
async def test_invoke_uses_convention_service():
    reg = SkillRegistry()
    reg.register_plugin_skills("demo", "1.0.0", [{"name": "snap", "intent": "snap"}])
    runtime = SimpleNamespace(
        service_registry=_Registry({"demo.skill.snap": lambda **kw: {"ok": True}})
    )
    mod = SkillsModule(runtime)
    mod.registry = reg
    out = await mod._service_invoke("demo.snap", params={})
    assert out["ok"] is True
    assert out["service"] == "demo.skill.snap"


@pytest.mark.asyncio
async def test_invoke_not_configured_when_service_missing():
    reg = SkillRegistry()
    reg.register_plugin_skills("demo", "1.0.0", [{"name": "snap", "intent": "snap"}])
    runtime = SimpleNamespace(
        service_registry=_Registry({}),
        plugin_manager=_pm(object()),
    )
    mod = SkillsModule(runtime)
    mod.registry = reg
    out = await mod._service_invoke("demo.snap", params={})
    assert out["ok"] is False
    assert out["code"] == "invoke_not_configured"
    assert out["error"] == "invoke not configured"


class _DemoPlugin:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def skill_snap(self, **kw):
        self.calls.append(kw)
        return {"via": "dotted", **kw}


class _NestedSkill:
    async def snap(self, **kw):
        return {"via": "nested", **kw}


class _DemoPluginNested:
    def __init__(self) -> None:
        self.skill = _NestedSkill()


def _pm(plugin, *, state: PluginState = PluginState.STARTED) -> MagicMock:
    pm = MagicMock()
    pm.get_plugin.return_value = plugin
    pm.get_plugin_state.return_value = state
    return pm


@pytest.mark.asyncio
async def test_invoke_dotted_path_without_register_service():
    reg = SkillRegistry()
    reg.register_plugin_skills("demo", "1.0.0", [{"name": "snap", "intent": "snap"}])
    plugin = _DemoPluginNested()
    runtime = SimpleNamespace(
        service_registry=_Registry({}),
        plugin_manager=_pm(plugin),
    )
    mod = SkillsModule(runtime)
    mod.registry = reg
    out = await mod._service_invoke("demo.snap", params={"n": 3})
    assert out["ok"] is True
    assert out["service"] == "demo.skill.snap"
    assert out["result"] == {"via": "nested", "n": 3}


@pytest.mark.asyncio
async def test_invoke_dotted_path_underscore_fallback():
    reg = SkillRegistry()
    reg.register_plugin_skills("demo", "1.0.0", [{"name": "snap", "intent": "snap"}])
    plugin = _DemoPlugin()
    runtime = SimpleNamespace(
        service_registry=_Registry({}),
        plugin_manager=_pm(plugin),
    )
    mod = SkillsModule(runtime)
    mod.registry = reg
    out = await mod._service_invoke("demo.snap", params={"x": 1})
    assert out["ok"] is True
    assert out["service"] == "demo.skill.snap"
    assert out["result"] == {"via": "dotted", "x": 1}
    assert plugin.calls == [{"x": 1}]


@pytest.mark.asyncio
async def test_invoke_plugin_not_started_returns_plugin_not_started():
    reg = SkillRegistry()
    reg.register_plugin_skills("demo", "1.0.0", [{"name": "snap", "intent": "snap"}])
    plugin = _DemoPlugin()
    runtime = SimpleNamespace(
        service_registry=_Registry({}),
        plugin_manager=_pm(plugin, state=PluginState.LOADED),
    )
    mod = SkillsModule(runtime)
    mod.registry = reg
    out = await mod._service_invoke("demo.snap", params={})
    assert out["ok"] is False
    assert out["code"] == "plugin_not_started"
