"""Credential rotation scheduling logic."""

import heapq
from datetime import datetime, timezone
from typing import Optional, Dict, Set
import asyncio

from .policy import RotationPolicy, RotationState, RotationStatus
from .exceptions import RotationException


class RotationScheduler:
    """
    Schedules credential rotations.
    
    Maintains:
    - In-memory priority queue (heap) of due rotations
    - Mapping of credential_id to rotation state
    - Periodic background check task
    
    Uses a min-heap ordered by next_rotation_at timestamp.
    """
    
    def __init__(self, check_interval_seconds: int = 60):
        """
        Initialize rotation scheduler.
        
        Args:
            check_interval_seconds: How often to check for due rotations (default: 60)
        """
        self.check_interval_seconds = check_interval_seconds
        self._heap: list[tuple[str, str]] = []  # (next_rotation_at, credential_id)
        self._states: Dict[str, RotationState] = {}  # credential_id -> state
        self._running = False
        self._lock = asyncio.Lock()  # Protect heap and state dict
        self._check_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start background rotation check task."""
        if self._running:
            return
        
        self._running = True
        self._check_task = asyncio.create_task(self._periodic_check())
    
    async def stop(self) -> None:
        """Stop background rotation check task."""
        self._running = False
        
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
    
    async def schedule(
        self,
        credential_id: str,
        rotation_policy: RotationPolicy,
        last_rotated_at: Optional[str] = None,
    ) -> None:
        """
        Schedule a credential for rotation.
        
        Args:
            credential_id: ID of credential
            rotation_policy: Rotation policy
            last_rotated_at: When it was last rotated (optional)
        """
        async with self._lock:
            # Calculate next rotation time
            next_rotation_at = rotation_policy.next_rotation_due(last_rotated_at)
            
            # Create or update state
            if credential_id in self._states:
                old_state = self._states[credential_id]
                self._states[credential_id] = RotationState(
                    last_rotated_at=last_rotated_at,
                    next_rotation_at=next_rotation_at,
                    rotation_status=RotationStatus.SCHEDULED,
                    failure_count=old_state.failure_count,
                    last_failure_reason=old_state.last_failure_reason,
                )
            else:
                self._states[credential_id] = RotationState(
                    last_rotated_at=last_rotated_at,
                    next_rotation_at=next_rotation_at,
                    rotation_status=RotationStatus.SCHEDULED,
                )
            
            # Add to heap
            heapq.heappush(self._heap, (next_rotation_at, credential_id))
    
    async def get_due_rotations(self) -> list[str]:
        """
        Get list of credential IDs with rotations currently due.
        
        Returns:
            List of credential IDs that need rotation
        """
        async with self._lock:
            due = []
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            
            # Peek at heap (don't remove yet, in case of failures)
            for rotation_time, cred_id in self._heap:
                if rotation_time <= now:
                    state = self._states.get(cred_id)
                    if state and state.rotation_status in (
                        RotationStatus.SCHEDULED,
                        RotationStatus.IDLE,
                    ):
                        due.append(cred_id)
            
            return due
    
    async def mark_rotation_started(self, credential_id: str) -> None:
        """Mark that rotation has started for a credential."""
        async with self._lock:
            if credential_id in self._states:
                state = self._states[credential_id]
                self._states[credential_id] = RotationState(
                    last_rotated_at=state.last_rotated_at,
                    next_rotation_at=state.next_rotation_at,
                    rotation_status=RotationStatus.IN_PROGRESS,
                    failure_count=state.failure_count,
                )
    
    async def mark_rotation_completed(
        self,
        credential_id: str,
        new_last_rotated_at: str,
        rotation_policy: RotationPolicy,
    ) -> None:
        """
        Mark that rotation completed successfully.
        
        Reschedules next rotation based on policy.
        
        Args:
            credential_id: ID of credential
            new_last_rotated_at: New last-rotated timestamp
            rotation_policy: Policy for next rotation
        """
        async with self._lock:
            # Calculate next rotation from current time
            next_rotation_at = rotation_policy.next_rotation_due(new_last_rotated_at)
            
            self._states[credential_id] = RotationState(
                last_rotated_at=new_last_rotated_at,
                next_rotation_at=next_rotation_at,
                rotation_status=RotationStatus.IDLE,
                failure_count=0,
                last_failure_reason=None,
            )
            
            # Re-add to heap for next interval
            heapq.heappush(self._heap, (next_rotation_at, credential_id))
    
    async def mark_rotation_failed(
        self,
        credential_id: str,
        error_reason: str,
        max_failures: int = 3,
    ) -> bool:
        """
        Mark that rotation failed.
        
        Tracks failure count. If exceeds max, sets to FAILED status.
        
        Args:
            credential_id: ID of credential
            error_reason: Error message
            max_failures: Max failures before giving up
        
        Returns:
            True if failure count exceeded max, False otherwise
        """
        async with self._lock:
            state = self._states.get(credential_id)
            if not state:
                return False
            
            new_failure_count = state.failure_count + 1
            
            if new_failure_count >= max_failures:
                # Too many failures - give up
                self._states[credential_id] = RotationState(
                    last_rotated_at=state.last_rotated_at,
                    next_rotation_at=state.next_rotation_at,
                    rotation_status=RotationStatus.FAILED,
                    failure_count=new_failure_count,
                    last_failure_reason=error_reason,
                )
                return True
            else:
                # Retry later
                self._states[credential_id] = RotationState(
                    last_rotated_at=state.last_rotated_at,
                    next_rotation_at=state.next_rotation_at,
                    rotation_status=RotationStatus.SCHEDULED,
                    failure_count=new_failure_count,
                    last_failure_reason=error_reason,
                )
                return False
    
    async def cancel_rotation(self, credential_id: str) -> None:
        """Cancel scheduled rotation."""
        async with self._lock:
            if credential_id in self._states:
                state = self._states[credential_id]
                self._states[credential_id] = RotationState(
                    last_rotated_at=state.last_rotated_at,
                    next_rotation_at=state.next_rotation_at,
                    rotation_status=RotationStatus.IDLE,
                    failure_count=0,
                )
    
    async def get_state(self, credential_id: str) -> Optional[RotationState]:
        """Get rotation state for a credential."""
        async with self._lock:
            return self._states.get(credential_id)
    
    async def _periodic_check(self) -> None:
        """Periodic background task to check for due rotations."""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval_seconds)
                
                # Clean up stale heap entries
                async with self._lock:
                    while self._heap:
                        rotation_time, cred_id = self._heap[0]
                        
                        # Check if this entry is still valid
                        state = self._states.get(cred_id)
                        if state is None or (
                            state.rotation_status != RotationStatus.SCHEDULED
                            and state.rotation_status != RotationStatus.IDLE
                        ):
                            # Remove stale entry
                            heapq.heappop(self._heap)
                        else:
                            break  # Heap is valid from this point
                        
            except asyncio.CancelledError:
                break
            except Exception:
                # Continue on errors (don't crash background task)
                continue
