import pytest
from fastapi import Response

from modules.api.route_binding import _normalize_api_error, _normalize_api_result


def test_normalize_api_result_preserves_ok_dict():
    assert _normalize_api_result({"ok": True, "x": 1}) == {"ok": True, "x": 1}
    assert _normalize_api_result({"ok": False, "error": "nope"}) == {
        "ok": False,
        "error": "nope",
    }


def test_normalize_api_result_wraps_raw_payload():
    assert _normalize_api_result(["a", "b"]) == {"ok": True, "result": ["a", "b"]}
    assert _normalize_api_result(123) == {"ok": True, "result": 123}


def test_normalize_api_error_sets_status_and_payload():
    resp = Response()
    payload = _normalize_api_error(resp, 403, "Forbidden", code="FORBIDDEN")
    assert resp.status_code == 403
    assert payload == {"ok": False, "error": "Forbidden", "code": "FORBIDDEN"}

