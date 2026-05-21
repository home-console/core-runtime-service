"""Tests for core.kernel.plugin_manifest_schema."""

import pytest

from core.kernel.plugin_manifest_schema import ValidationError, validate_plugin_json


def _minimal(**extra):
    base = {
        "name": "demo_plugin",
        "version": "1.0.0",
        "description": "Demo",
        "author": "Test",
        "class_path": "plugins.demo_plugin.plugin.Plugin",
    }
    base.update(extra)
    return base


def test_valid_minimal():
    m = validate_plugin_json(_minimal())
    assert m["name"] == "demo_plugin"


def test_skills_and_cli():
    m = validate_plugin_json(
        _minimal(
            cli={"subcommands": [{"name": "run", "module": "./cli/run.py"}]},
            skills=[{"name": "skill_a", "intent": "do something"}],
        )
    )
    assert m["cli"]["subcommands"][0]["name"] == "run"
    assert m["skills"][0]["name"] == "skill_a"


def test_agent_skills_rejected_use_skills():
    with pytest.raises(ValidationError, match="skills"):
        validate_plugin_json(
            _minimal(agent_skills=[{"name": "legacy", "intent": "legacy intent"}]),
        )


def test_invalid_semver():
    with pytest.raises(ValidationError, match="version"):
        validate_plugin_json(_minimal(version="not-semver"))


def test_both_ui_and_ui_contributions_rejected():
    with pytest.raises(ValidationError, match="ui_contributions"):
        validate_plugin_json(_minimal(ui={"pages": []}, ui_contributions={"pages": []}))


def test_ui_page_server_driven_settings():
    m = validate_plugin_json(
        _minimal(
            ui={
                "pages": [
                    {
                        "path": "/plugins/demo/settings",
                        "type": "settings",
                        "config_schema": {"type": "object", "properties": {"enabled": {"type": "boolean"}}},
                    }
                ],
            }
        )
    )
    assert m["ui"]["pages"][0]["type"] == "settings"
    assert "module" not in m["ui"]["pages"][0]


def test_ui_page_server_driven_metric_requires_service():
    m = validate_plugin_json(
        _minimal(
            ui={
                "pages": [
                    {
                        "path": "/plugins/demo/metric",
                        "type": "metric",
                        "service": "demo.get_value",
                    }
                ],
            }
        )
    )
    assert m["ui"]["pages"][0]["service"] == "demo.get_value"

    with pytest.raises(ValidationError, match="service"):
        validate_plugin_json(
            _minimal(ui={"pages": [{"path": "/m", "type": "metric"}]}),
        )


def test_ui_page_type_and_module_mutually_exclusive():
    with pytest.raises(ValidationError, match="not both"):
        validate_plugin_json(
            _minimal(
                ui={
                    "pages": [
                        {
                            "path": "/x",
                            "type": "settings",
                            "module": "./ui/page.js",
                        }
                    ],
                }
            ),
        )


def test_ui_dashboard_card_metric():
    m = validate_plugin_json(
        _minimal(
            ui={
                "dashboard_cards": [
                    {"id": "temp", "type": "metric", "service": "demo.get_temp", "title": "Temp"},
                ],
            }
        )
    )
    assert m["ui"]["dashboard_cards"][0]["type"] == "metric"


def test_ui_page_legacy_module_still_valid():
    m = validate_plugin_json(
        _minimal(ui={"pages": [{"path": "/legacy", "module": "./ui/page.js"}]}),
    )
    assert m["ui"]["pages"][0]["module"] == "./ui/page.js"
