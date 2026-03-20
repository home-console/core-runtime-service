"""
AgentLogStore — In-memory log buffer for remote agents.

Each agent gets a ring buffer of MAX_LOGS_PER_AGENT entries.
Logs are pushed by agents (via /agents/{id}/logs POST) and
retrieved by admins (via /agents/{id}/logs GET).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

MAX_LOGS_PER_AGENT = 1000
MAX_LOG_MESSAGE_LEN = 4096


@dataclass
class LogEntry:
    timestamp: str
    level: str
    message: str
    source: str = "agent"
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        d: Dict = {
            "timestamp": self.timestamp,
            "level": self.level,
            "message": self.message,
            "source": self.source,
        }
        if self.metadata:
            d["metadata"] = self.metadata
        return d


_VALID_LEVELS = {"debug", "info", "warn", "warning", "error", "critical"}


class AgentLogStore:
    """Thread-safe (asyncio-safe) per-agent log ring buffer."""

    def __init__(self, max_per_agent: int = MAX_LOGS_PER_AGENT):
        self._max = max_per_agent
        self._store: Dict[str, deque] = {}

    def push(
        self,
        agent_id: str,
        level: str,
        message: str,
        source: str = "agent",
        timestamp: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> LogEntry:
        if agent_id not in self._store:
            self._store[agent_id] = deque(maxlen=self._max)

        level = level.lower()
        if level not in _VALID_LEVELS:
            level = "info"
        if level == "warning":
            level = "warn"

        if len(message) > MAX_LOG_MESSAGE_LEN:
            message = message[:MAX_LOG_MESSAGE_LEN] + "…"

        entry = LogEntry(
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
            level=level,
            message=message,
            source=source,
            metadata=metadata or {},
        )
        self._store[agent_id].append(entry)
        return entry

    def push_batch(self, agent_id: str, entries: List[Dict]) -> int:
        added = 0
        for e in entries:
            if not isinstance(e, dict):
                continue
            msg = e.get("message", "")
            if not msg:
                continue
            self.push(
                agent_id=agent_id,
                level=e.get("level", "info"),
                message=msg,
                source=e.get("source", "agent"),
                timestamp=e.get("timestamp"),
                metadata=e.get("metadata"),
            )
            added += 1
        return added

    def get(
        self,
        agent_id: str,
        *,
        level_filter: Optional[str] = None,
        tail: Optional[int] = None,
    ) -> List[LogEntry]:
        buf = self._store.get(agent_id)
        if buf is None:
            return []

        entries: List[LogEntry] = list(buf)

        if level_filter:
            levels = {lvl.strip().lower() for lvl in level_filter.split(",")}
            if "warning" in levels:
                levels.discard("warning")
                levels.add("warn")
            entries = [e for e in entries if e.level in levels]

        if tail is not None and tail > 0:
            entries = entries[-tail:]

        return entries

    def clear(self, agent_id: str) -> int:
        buf = self._store.pop(agent_id, None)
        return len(buf) if buf else 0

    def clear_all(self) -> None:
        self._store.clear()

    def agent_ids(self) -> List[str]:
        return list(self._store.keys())

    def count(self, agent_id: str) -> int:
        buf = self._store.get(agent_id)
        return len(buf) if buf else 0
