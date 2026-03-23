from typing import Any


async def handle_automation_run(params: dict[str, Any]) -> dict[str, Any]:
    external_id = params.get("external_id")
    if not external_id:
        raise ValueError("external_id is required")

    return {
        "ok": True,
        "source_event": params.get("source_event", "external.device_state_reported"),
        "external_id": external_id,
        "internal_id": params.get("internal_id"),
        "reported_state": params.get("reported_state", params.get("state")),
        "raw": params.get("raw", params),
    }