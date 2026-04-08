"""Стабильность контракта dedup (G1): ключи и namespace не должны меняться без миграции."""

import pytest

from core.operations.dedup_contract import (
    DEFAULT_DEDUP_TTL_SECONDS,
    DEDUP_STORAGE_NAMESPACE,
    OPERATION_READY_EVENT_TYPE,
    PROCESSED_EVENT_KEY_PREFIX,
    PROCESSED_OPERATION_KEY_PREFIX,
    storage_key_for_event,
    storage_key_for_operation,
)
from sdk.operations_events import (
    OPERATION_READY_EVENT_TYPE as SDK_OPERATION_READY,
    build_operation_ready_payload,
)


def test_storage_namespace_unchanged():
    assert DEDUP_STORAGE_NAMESPACE == "dedup"


def test_operation_ready_event_type_unchanged():
    assert OPERATION_READY_EVENT_TYPE == "operation_ready"
    assert SDK_OPERATION_READY is OPERATION_READY_EVENT_TYPE


def test_key_prefixes_unchanged():
    assert PROCESSED_OPERATION_KEY_PREFIX == "processed_op:"
    assert PROCESSED_EVENT_KEY_PREFIX == "processed_event:"


def test_storage_key_builders():
    assert storage_key_for_operation("op-abc") == "processed_op:op-abc"
    assert storage_key_for_event("evt-deadbeef") == "processed_event:evt-deadbeef"


def test_default_ttl_positive():
    assert DEFAULT_DEDUP_TTL_SECONDS == 3600


def test_build_operation_ready_payload_canonical():
    p = build_operation_ready_payload("op-1", operation_type="x.y")
    assert p["type"] == "operation_ready"
    assert p["operation_id"] == "op-1"
    assert p["operation_type"] == "x.y"


def test_build_operation_ready_payload_rejects_bad_id():
    with pytest.raises(ValueError):
        build_operation_ready_payload("")
    with pytest.raises(ValueError):
        build_operation_ready_payload(None)  # type: ignore[arg-type]


def test_build_operation_ready_overrides_bad_extra_type():
    p = build_operation_ready_payload("op-2", type="wrong")
    assert p["type"] == "operation_ready"
