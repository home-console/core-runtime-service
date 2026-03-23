from typing import Any


def device_state_to_operation(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "op_type": "automation.run",
        "params": {
            "source_event": data.get("source_event", "external.device_state_reported"),
            "external_id": data["external_id"],
            "internal_id": data.get("internal_id"),
            "reported_state": data.get("reported_state", data.get("state")),
            "raw": data.get("raw", data),
        },
    }