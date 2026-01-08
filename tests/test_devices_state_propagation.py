"""
Integration test: State propagation from external → internal devices via event_bus.

Scenario:
1. Create external device (mock).
2. Create internal device and mapping.
3. Publish external.device_state_reported event.
4. Verify internal device state is updated.
5. Verify internal.device_state_updated event is published.
"""

import asyncio
import pytest
from core.runtime import CoreRuntime


@pytest.mark.asyncio
async def test_state_propagation_via_event_bus(memory_adapter):
    """Test that external device state propagates to internal device via event_bus."""

    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    # give plugins a moment to finish initialization/subscriptions
    await asyncio.sleep(0.01)

    try:
        # 1. Create an external device
        external_id = "test-ext-light-001"
        external_payload = {
            "provider": "yandex",
            "external_id": external_id,
            "name": "Test Light",
            "type": "light",
            "capabilities": ["on_off", "brightness"],
            "state": {"on": False, "brightness": 0},
        }
        await runtime.storage.set("devices_external", external_id, external_payload)

        # 2. Create an internal device and mapping
        internal_id = "yandex-test-ext-light-001"
        internal_device = {
            "id": internal_id,
            "name": "Test Light",
            "type": "light",
            "state": {"on": False, "brightness": 0},
        }
        await runtime.storage.set("devices", internal_id, internal_device)
        await runtime.storage.set("devices_mappings", external_id, internal_id)

        # Track events published
        published_events = []
        
        async def track_events(event_type, data):
            published_events.append({"type": event_type, "data": data})

        runtime.event_bus.subscribe("internal.device_state_updated", track_events)

        # 3. Publish external state change event
        external_state_update = {
            "external_id": external_id,
            "state": {"on": True, "brightness": 75},
        }
        await runtime.event_bus.publish("external.device_state_reported", external_state_update)

        # Allow event handlers to run
        await asyncio.sleep(0.2)

        # 4. Verify internal device state was updated
        updated_device = await runtime.storage.get("devices", internal_id)
        assert updated_device is not None
        assert updated_device["state"]["on"] is True
        assert updated_device["state"]["brightness"] == 75

        # 5. Verify internal.device_state_updated event was published
        assert len(published_events) > 0
        event = published_events[0]
        assert event["type"] == "internal.device_state_updated"
        assert event["data"]["internal_id"] == internal_id
        assert event["data"]["external_id"] == external_id
        assert event["data"]["new_state"]["on"] is True
        assert event["data"]["new_state"]["brightness"] == 75

        print("✓ State propagation test passed")
        print(f"  External state: {external_state_update['state']}")
        print(f"  Internal state: {updated_device['state']}")
        print(f"  Events published: {len(published_events)}")

    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_state_propagation_no_mapping(memory_adapter):
    """Test that unmapped external state is ignored."""

    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    await asyncio.sleep(0.01)

    try:
        external_id = "unmapped-ext-001"
        
        # Track events (should be none)
        published_events = []
        
        async def track_events(event_type, data):
            published_events.append({"type": event_type, "data": data})

        runtime.event_bus.subscribe("internal.device_state_updated", track_events)

        # Publish state for unmapped device
        await runtime.event_bus.publish("external.device_state_reported", {
            "external_id": external_id,
            "state": {"on": True},
        })

        # Allow time for handlers to run
        await asyncio.sleep(0.2)

        # Should have no events (no mapping)
        assert len(published_events) == 0
        print("✓ Unmapped device state ignored correctly")

    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_state_propagation_merge(memory_adapter):
    """Test that external state merges with existing internal state."""

    runtime = CoreRuntime(memory_adapter)
    await runtime.start()
    await asyncio.sleep(0.01)

    try:
        external_id = "test-ext-ac-001"
        internal_id = "yandex-test-ext-ac-001"

        # Create internal device with initial state
        initial_state = {
            "on": True,
            "mode": "cool",
            "temperature": 20,
            "custom_field": "should_persist",
        }
        internal_device = {
            "id": internal_id,
            "name": "Test AC",
            "type": "ac",
            "state": initial_state,
        }
        await runtime.storage.set("devices", internal_id, internal_device)
        await runtime.storage.set("devices_mappings", external_id, internal_id)

        # Publish partial state update from external
        partial_update = {
            "on": False,
            "temperature": 22,
        }
        await runtime.event_bus.publish("external.device_state_reported", {
            "external_id": external_id,
            "state": partial_update,
        })

        # Allow handlers to run
        await asyncio.sleep(0.2)

        # Verify merged state
        updated_device = await runtime.storage.get("devices", internal_id)
        merged_state = updated_device["state"]

        # Updated fields
        assert merged_state["on"] is False
        assert merged_state["temperature"] == 22
        # Preserved fields
        assert merged_state["mode"] == "cool"
        assert merged_state["custom_field"] == "should_persist"

        print("✓ State merge test passed")
        print(f"  Initial state: {initial_state}")
        print(f"  Update: {partial_update}")
        print(f"  Merged state: {merged_state}")

    finally:
        await runtime.stop()
