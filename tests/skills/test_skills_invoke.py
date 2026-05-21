from __future__ import annotations

from types import SimpleNamespace

import pytest

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
    runtime = SimpleNamespace(service_registry=_Registry({}))
    mod = SkillsModule(runtime)
    mod.registry = reg
    out = await mod._service_invoke("demo.snap", params={})
    assert out["ok"] is False
    assert out["code"] == "invoke_not_configured"
    assert out["error"] == "invoke not configured"
