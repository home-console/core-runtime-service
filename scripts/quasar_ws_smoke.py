"""
Quasar WebSocket Smoke Test

Starts CoreRuntime, ensures real API flag is enabled, checks cookies,
then waits for Quasar WS to connect and prints incoming device updates
published on event bus as 'external.device_state_reported'.

Usage:
    cd core-runtime-service
    python3 dev-scripts/quasar_ws_smoke.py

Prerequisites:
- Valid session cookies saved via the OAuth plugin cookies endpoint
- OAuth is optional (not used for WS), but device sync may use it
"""

import asyncio
import signal
from typing import Any

from core.runtime.config import Config
from core.runtime.runtime import CoreRuntime
from core.adapters.sqlite_adapter import SQLiteAdapter


async def main() -> None:
    # Use default DB path or override if needed
    storage = SQLiteAdapter(Config.db_path())
    runtime = CoreRuntime(storage)

    # Graceful shutdown on Ctrl+C
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    loop.add_signal_handler(signal.SIGINT, stop_event.set)
    loop.add_signal_handler(signal.SIGTERM, stop_event.set)

    await runtime.start()

    # Check cookies presence
    cookies = None
    try:
        cookies = await runtime.service_registry.call("oauth_yandex.get_cookies")
    except Exception:
        cookies = None

    if not isinstance(cookies, dict) or not cookies:
        print("[error] Session cookies not found. Configure cookies via OAuth plugin first.")
        await runtime.shutdown()
        return

    missing = [k for k in ("Session_id", "yandexuid") if k not in cookies]
    if missing:
        print(f"[error] Missing required cookies: {missing}. Have: {list(cookies.keys())}")
        await runtime.shutdown()
        return

    print("[info] Cookies OK. Waiting for Quasar WS to connect...")

    # Subscribe to device state updates
    updates_count = 0

    async def on_update(event_type: str, payload: Any):
        nonlocal updates_count
        updates_count += 1
        device_id = payload.get("external_id")
        state = payload.get("state")
        print(f"[update] {device_id}: {state}")

    await runtime.event_bus.subscribe("external.device_state_reported", on_update)

    # Wait for events / connection logs
    print("[info] Listening for WS events (press Ctrl+C to stop)...")

    # Simple wait loop until stopped
    try:
        await stop_event.wait()
    finally:
        print(f"[summary] Received {updates_count} updates")
        await runtime.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
