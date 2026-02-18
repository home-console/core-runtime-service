"""
Elevation Session Manager — In-memory, TTL-based session registry for elevated access.

Sessions are:
- Memory-only (never persisted)
- Time-limited (configurable TTL, default 90 seconds)
- Thread-safe (asyncio-safe)
- Auto-cleaned on access

Design: Elevation grants temporary permission to access secrets without re-auth.

Example lifecycle:
    1. User requests secret read
    2. No elevation session → MFARequired exception
    3. User submits TOTP code → MFAService.verify_and_elevate()
    4. Creates session with TTL 90s → AuditBinder logs elevation
    5. User retries secret read
    6. Session valid + not expired → secret returned
    7. 90s later → session auto-expires
"""

import asyncio
import time
from dataclasses import dataclass
from typing import Optional, Dict
from datetime import datetime


@dataclass(frozen=True)
class ElevationSession:
    """Immutable elevation session record."""
    
    user_id: str
    elevation_level: str  # e.g., "secret_read"
    created_at: float  # Unix timestamp
    expires_at: float  # Unix timestamp
    mfa_method_used: str  # e.g., "totp"
    
    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return time.time() >= self.expires_at
    
    @property
    def remaining_seconds(self) -> float:
        """Seconds until expiration (0 if expired)."""
        remaining = self.expires_at - time.time()
        return max(0, remaining)
    
    def to_dict(self) -> dict:
        """Serialize to dict for audit logging."""
        return {
            "user_id": self.user_id,
            "elevation_level": self.elevation_level,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "mfa_method_used": self.mfa_method_used,
            "remaining_seconds": self.remaining_seconds,
        }


class ElevationSessionManager:
    """
    Manages in-memory elevation sessions with TTL enforcement.
    
    Thread-safe (asyncio-safe, uses locks for concurrent access).
    
    Design:
    - One session per user (per elevation_level)
    - Auto-cleanup on access
    - No persistence
    - Survives process but lost on restart (by design)
    """
    
    def __init__(self, cleanup_interval: int = 30):
        """
        Initialize manager.
        
        Args:
            cleanup_interval: Seconds between cleanup runs (default 30)
        """
        self._sessions: Dict[str, Dict[str, ElevationSession]] = {}
        # sessions[user_id][elevation_level] → ElevationSession
        
        self._lock = asyncio.Lock()
        self._cleanup_interval = cleanup_interval
        self._cleanup_task = None
    
    async def start_cleanup(self) -> None:
        """Start background cleanup task."""
        if self._cleanup_task:
            return
        
        async def cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(self._cleanup_interval)
                    await self.cleanup_expired()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[WARNING] Elevation session cleanup error: {e}")
        
        self._cleanup_task = asyncio.create_task(cleanup_loop())
    
    async def stop_cleanup(self) -> None:
        """Stop background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
    
    async def create_session(
        self,
        user_id: str,
        elevation_level: str,
        mfa_method_used: str,
        ttl_seconds: int = 90,
    ) -> ElevationSession:
        """
        Create new elevation session.
        
        Args:
            user_id: User identifier
            elevation_level: Access level (e.g., "secret_read")
            mfa_method_used: MFA method used (e.g., "totp")
            ttl_seconds: Time-to-live in seconds (default 90)
        
        Returns:
            ElevationSession
        """
        now = time.time()
        session = ElevationSession(
            user_id=user_id,
            elevation_level=elevation_level,
            created_at=now,
            expires_at=now + ttl_seconds,
            mfa_method_used=mfa_method_used,
        )
        
        async with self._lock:
            if user_id not in self._sessions:
                self._sessions[user_id] = {}
            
            self._sessions[user_id][elevation_level] = session
        
        return session
    
    async def get_session(
        self,
        user_id: str,
        elevation_level: str,
    ) -> Optional[ElevationSession]:
        """
        Get elevation session (returns None if expired or not found).
        
        Args:
            user_id: User identifier
            elevation_level: Access level
        
        Returns:
            ElevationSession or None
        """
        async with self._lock:
            if user_id not in self._sessions:
                return None
            
            session = self._sessions[user_id].get(elevation_level)
            
            if session and session.is_expired:
                # Auto-clean expired session
                del self._sessions[user_id][elevation_level]
                if not self._sessions[user_id]:
                    del self._sessions[user_id]
                return None
            
            return session
    
    async def validate_session(
        self,
        user_id: str,
        elevation_level: str,
    ) -> bool:
        """
        Check if user has valid elevation session for requested level.
        
        Returns:
            True if session exists and is not expired
        """
        session = await self.get_session(user_id, elevation_level)
        return session is not None
    
    async def revoke_session(
        self,
        user_id: str,
        elevation_level: str = None,
    ) -> bool:
        """
        Revoke elevation session(s).
        
        Args:
            user_id: User identifier
            elevation_level: If provided, revoke only this level; else revoke all
        
        Returns:
            True if session(s) were revoked
        """
        async with self._lock:
            if user_id not in self._sessions:
                return False
            
            if elevation_level:
                # Revoke specific level
                if elevation_level in self._sessions[user_id]:
                    del self._sessions[user_id][elevation_level]
                    if not self._sessions[user_id]:
                        del self._sessions[user_id]
                    return True
                return False
            else:
                # Revoke all levels for user
                if self._sessions[user_id]:
                    del self._sessions[user_id]
                    return True
                return False
    
    async def cleanup_expired(self) -> int:
        """
        Remove all expired sessions.
        
        Returns:
            Number of sessions cleaned
        """
        cleaned = 0
        
        async with self._lock:
            users_to_delete = []
            
            for user_id, levels in list(self._sessions.items()):
                levels_to_delete = []
                
                for level, session in list(levels.items()):
                    if session.is_expired:
                        levels_to_delete.append(level)
                        cleaned += 1
                
                # Delete expired levels
                for level in levels_to_delete:
                    del levels[level]
                
                # Delete user if no sessions remain
                if not levels:
                    users_to_delete.append(user_id)
            
            # Delete empty user entries
            for user_id in users_to_delete:
                del self._sessions[user_id]
        
        return cleaned
    
    async def get_user_sessions(self, user_id: str) -> Dict[str, ElevationSession]:
        """Get all active sessions for user."""
        async with self._lock:
            if user_id not in self._sessions:
                return {}
            
            # Filter expired
            return {
                level: session
                for level, session in self._sessions[user_id].items()
                if not session.is_expired
            }
    
    async def get_all_sessions(self) -> Dict[str, Dict[str, ElevationSession]]:
        """Get all active sessions (for monitoring/debugging)."""
        async with self._lock:
            # Filter expired
            result = {}
            for user_id, levels in self._sessions.items():
                active_levels = {
                    level: session
                    for level, session in levels.items()
                    if not session.is_expired
                }
                if active_levels:
                    result[user_id] = active_levels
            return result
    
    async def stats(self) -> dict:
        """Get session statistics."""
        async with self._lock:
            total_users = len(self._sessions)
            total_sessions = sum(
                len(levels) for levels in self._sessions.values()
            )
            
            return {
                "total_users": total_users,
                "total_sessions": total_sessions,
                "average_per_user": total_sessions / max(total_users, 1),
            }
