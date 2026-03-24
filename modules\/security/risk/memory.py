"""
Risk Memory — In-memory event storage with sliding window and TTL pruning.

Design:
- Per-user ring buffer (bounded memory)
- Sliding window based on timestamp
- Background cleanup task
- Async-safe with locks
- O(1) insert, O(n) scan

Properties:
- Memory-only (no persistence)
- Configurable window
- Automatic TTL expiration
"""

from typing import Dict, List, Optional
import asyncio
import time

from core.security.risk.models import RiskEvent, RiskConfig


class RiskMemory:
    """In-memory event storage for risk scoring."""
    
    def __init__(self, config: RiskConfig = None):
        """
        Initialize risk memory.
        
        Args:
            config: RiskConfig (uses defaults if None)
        """
        self.config = config or RiskConfig()
        self.config.validate()
        
        # Per-user event storage: user_id → list of (event, time_added)
        self._events: Dict[str, List[RiskEvent]] = {}
        
        # Lock for async safety
        self._lock = asyncio.Lock()
        
        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def record(self, event: RiskEvent) -> None:
        """
        Record a risk event.
        
        Args:
            event: RiskEvent to record
        """
        async with self._lock:
            user_id = event.user_id
            if user_id not in self._events:
                self._events[user_id] = []
            
            # Add event
            self._events[user_id].append(event)
            
            # Enforce max size (ring buffer behavior - remove oldest)
            if len(self._events[user_id]) > self.config.max_events_per_user:
                self._events[user_id].pop(0)
    
    async def get_recent(
        self,
        user_id: str,
        current_time: Optional[float] = None,
    ) -> List[RiskEvent]:
        """
        Get recent events for user (within window).
        
        Args:
            user_id: User identifier
            current_time: Current timestamp (uses now() if None)
        
        Returns:
            List of events within window
        """
        if current_time is None:
            current_time = time.time()
        
        async with self._lock:
            events = self._events.get(user_id, [])
            window_start = current_time - self.config.window_seconds
            
            # Filter to events within window
            return [
                e for e in events
                if e.timestamp >= window_start
            ]
    
    async def get_all_events(self, user_id: str) -> List[RiskEvent]:
        """Get all stored events for user (no time filter)."""
        async with self._lock:
            return list(self._events.get(user_id, []))
    
    async def clear_user(self, user_id: str) -> None:
        """Clear all events for user."""
        async with self._lock:
            if user_id in self._events:
                del self._events[user_id]
    
    async def cleanup_expired(self, current_time: Optional[float] = None) -> int:
        """
        Remove expired events (outside window).
        
        Args:
            current_time: Current timestamp (uses now() if None)
        
        Returns:
            Number of events removed
        """
        if current_time is None:
            current_time = time.time()
        
        window_start = current_time - self.config.window_seconds
        removed = 0
        
        async with self._lock:
            for user_id in list(self._events.keys()):
                before = len(self._events[user_id])
                
                # Remove old events
                self._events[user_id] = [
                    e for e in self._events[user_id]
                    if e.timestamp >= window_start
                ]
                
                removed += before - len(self._events[user_id])
                
                # Clean up empty entries
                if not self._events[user_id]:
                    del self._events[user_id]
        
        return removed
    
    async def start_cleanup(self) -> None:
        """Start background cleanup task."""
        if not self._running:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
    
    async def stop_cleanup(self) -> None:
        """Stop background cleanup task."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
    
    async def _cleanup_loop(self) -> None:
        """Background cleanup task."""
        while self._running:
            try:
                await asyncio.sleep(self.config.cleanup_interval)
                await self.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[ERROR] Cleanup loop failed: {e}")
    
    async def stats(self) -> dict:
        """Get memory statistics."""
        async with self._lock:
            total_events = sum(len(events) for events in self._events.values())
            return {
                "users_tracked": len(self._events),
                "total_events": total_events,
                "max_per_user": self.config.max_events_per_user,
            }
