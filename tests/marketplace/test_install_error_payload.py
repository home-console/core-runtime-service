"""Тесты разбора ошибок marketplace для ответа API."""

from modules.marketplace.install_error_payload import (
    generic_marketplace_failure_payload,
    installer_failure_payload,
    parse_marketplace_error_message,
)
from modules.marketplace.installer import InstallerError


def test_parse_known_prefix() -> None:
    stage, detail = parse_marketplace_error_message(
        "[marketplace:manifest] plugin.json does not match schema: x"
    )
    assert stage == "manifest"
    assert "plugin.json" in detail


def test_parse_unknown_string() -> None:
    stage, detail = parse_marketplace_error_message("plain failure")
    assert stage == "unknown"
    assert detail == "plain failure"


def test_installer_failure_payload_with_stage_attribute() -> None:
    exc = InstallerError("[marketplace:archive] missing", stage="archive")
    p = installer_failure_payload(exc)
    assert p["error_stage"] == "archive"
    assert "Подробнее:" in p["user_message"]
    assert p["error"] == "[marketplace:archive] missing"


def test_generic_reuses_known_prefix_without_subclass_attrs() -> None:
    msg = "[marketplace:integrity] SHA256 mismatch: a vs b"
    p = generic_marketplace_failure_payload(msg)
    assert p["error_stage"] == "integrity"
    assert "Подробнее:" in p["user_message"]
