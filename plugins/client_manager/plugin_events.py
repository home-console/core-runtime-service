"""
Bridge: re-exports plugin_events from the client-manager-service directory.
"""
import sys
from pathlib import Path

_service_dir = Path(__file__).resolve().parent.parent / "client-manager-service"
if _service_dir.is_dir() and str(_service_dir) not in sys.path:
    sys.path.insert(0, str(_service_dir))

from plugin_events import setup_event_integration, publish_heartbeat_event  # noqa: E402, F401
