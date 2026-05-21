from __future__ import annotations

from modules.skills.ingest import skills_from_manifest
from modules.skills.registry import SkillRegistry, skill_id


def test_skill_id_format():
    assert skill_id("demo", "read-temperature") == "demo.read-temperature"


def test_register_list_get_unregister():
    reg = SkillRegistry()
    ids = reg.register_plugin_skills(
        "demo",
        "1.0.0",
        [
            {"name": "read", "intent": "read sensor", "description": "  x  "},
            {"name": "bad", "intent": ""},
            "not-a-dict",
        ],
    )
    assert ids == ["demo.read"]
    assert len(reg.list_skills()) == 1
    rec = reg.get("demo.read")
    assert rec is not None
    assert rec.intent == "read sensor"
    assert rec.description == "x"
    assert reg.list_skills(plugin_name="demo")[0].id == "demo.read"
    assert reg.list_skills(plugin_name="other") == []
    assert reg.unregister_plugin("demo") == 1
    assert reg.list_skills() == []


def test_register_replaces_previous_plugin_skills():
    reg = SkillRegistry()
    reg.register_plugin_skills("p", "1.0.0", [{"name": "a", "intent": "i"}])
    reg.register_plugin_skills("p", "2.0.0", [{"name": "b", "intent": "j"}])
    assert reg.get("p.a") is None
    assert reg.get("p.b") is not None
    assert reg.get("p.b").plugin_version == "2.0.0"


def test_skills_from_manifest():
    assert skills_from_manifest(None) == []
    assert skills_from_manifest({"skills": "nope"}) == []
    assert skills_from_manifest(
        {"skills": [{"name": "a", "intent": "b"}, 1]}
    ) == [{"name": "a", "intent": "b"}]
