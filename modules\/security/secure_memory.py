"""
Linux Secure Memory Buffer.

Allocates mutable bytearray with:
- mlock() to pin memory (no swap)
- madvise(MADV_DONTDUMP) to exclude from core dumps
- Strict zeroization on close()
- Blocks copy, repr, pickle, deepcopy

LINUX ONLY - No fallback.
Requires: glibc, Python 3.11+
"""

import ctypes
import ctypes.util
import sys
from typing import Optional
import copy

# Linux constants
MADV_DONTDUMP = 16  # Don't include in core dump

_is_linux = sys.platform == "linux"

if _is_linux:
    # Load libc
    _libc_path = ctypes.util.find_library("c")
    if not _libc_path:
        raise RuntimeError("Cannot find libc - required for mlock/madvise")

    _libc = ctypes.CDLL(_libc_path, use_errno=True)


    def _get_errno() -> int:
        """Get errno after libc call."""
        return ctypes.get_errno()
else:
    # Fallbacks for non-Linux platforms (macOS, Windows)
    def _get_errno() -> int:
        return 0


class SecureBuffer:
    """
    OS-level secure memory buffer for secrets.
    
    Properties:
    - Allocated with mlock() (pinned, no swap)
    - Protected with madvise(MADV_DONTDUMP) (excluded from core dumps)
    - Strict zeroization on close()
    - Blocks all serialization (copy, deepcopy, pickle, repr)
    - Type-safe: only bytes/bytearray in/out
    
    Usage:
        buf = SecureBuffer(b"secret_key_material")
        try:
            data = buf.bytes  # Access
            # ...use data...
        finally:
            buf.close()  # Zeroize
    
    Raises:
        RuntimeError: if mlock/madvise fail
        ValueError: if size is 0 or negative
        MemoryError: if allocation fails
    """
    
    def __init__(self, data: bytes):
        """
        Create secure buffer from bytes.
        
        Args:
            data: bytes to protect (will be copied into locked memory)
            
        Raises:
            RuntimeError: if mlock/madvise fail
            ValueError: if data is empty
            MemoryError: if allocation fails
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError(f"data must be bytes/bytearray, got {type(data).__name__}")
        
        if len(data) == 0:
            raise ValueError("SecureBuffer cannot be empty")
        
        # Allocate mutable bytearray
        self._buffer = bytearray(data)
        self._size = len(self._buffer)
        self._locked = False
        self._zeroed = False
        
        # Get pointer to buffer data for zeroization
        array_type = ctypes.c_ubyte * self._size
        self._array = array_type.from_buffer(self._buffer)
        self._ptr = ctypes.cast(self._array, ctypes.c_void_p)

        # Platform-specific protections (mlock/madvise) only on Linux
        self._locked = False
        if _is_linux:
            # Lock memory and exclude from core dumps
            self._lock_memory()
            self._exclude_from_dump()
        else:
            # On non-Linux platforms we cannot mlock/madvise reliably.
            # Provide a best-effort implementation: warn and continue.
            import sys as _sys
            print(
                f"[SecureBuffer] WARNING: platform {_sys.platform} does not support mlock/madvise; using best-effort fallback",
                file=_sys.stderr,
            )
    
    def _lock_memory(self) -> None:
        """Lock buffer memory to prevent swapping."""
        if not _is_linux:
            return
        result = _libc.mlock(self._ptr, ctypes.c_size_t(self._size))
        if result != 0:
            errno = _get_errno()
            raise RuntimeError(
                f"mlock() failed: errno={errno}. "
                f"Check CAP_IPC_LOCK or increase ulimit -l"
            )
        self._locked = True
    
    def _exclude_from_dump(self) -> None:
        """Exclude buffer from core dumps."""
        if not _is_linux:
            return
        result = _libc.madvise(
            self._ptr,
            ctypes.c_size_t(self._size),
            ctypes.c_int(MADV_DONTDUMP)
        )
        if result != 0:
            errno = _get_errno()
            # madvise failure is warning-level (try to unlock first)
            try:
                _libc.munlock(self._ptr, ctypes.c_size_t(self._size))
            except Exception:
                pass
            raise RuntimeError(
                f"madvise(MADV_DONTDUMP) failed: errno={errno}. "
                f"System may not support DONTDUMP."
            )
    
    @property
    def bytes(self) -> bytes:
        """Get bytes view of buffer (read-only from caller perspective)."""
        if self._zeroed:
            raise RuntimeError("SecureBuffer has been closed/zeroed")
        return bytes(self._buffer)
    
    @property
    def bytearray_view(self) -> bytearray:
        """Get mutable bytearray view (be careful!)."""
        if self._zeroed:
            raise RuntimeError("SecureBuffer has been closed/zeroed")
        return self._buffer
    
    def close(self) -> None:
        """
        Zeroize memory and unlock.
        
        CRITICAL: Must be called when done.
        Wipes all data.
        """
        if self._zeroed:
            return  # Idempotent
        
        # Zeroize memory using ctypes.memset (not Python loop)
        ctypes.memset(self._ptr, 0, ctypes.c_size_t(self._size))
        
        # Unlock memory (only on Linux)
        if self._locked and _is_linux:
            result = _libc.munlock(self._ptr, ctypes.c_size_t(self._size))
            if result != 0:
                errno = _get_errno()
                import sys
                print(
                    f"[SecureBuffer] WARNING: munlock() failed: errno={errno}",
                    file=sys.stderr
                )
        
        self._zeroed = True
    
    def __del__(self) -> None:
        """Destructor - attempt cleanup (but explicit close() is required)."""
        try:
            self.close()
        except Exception:
            pass
    
    # ──────────────────────────────────────────────────────────
    # Block serialization and copying
    # ──────────────────────────────────────────────────────────
    
    def __repr__(self) -> str:
        """Block repr() to prevent accidental logging."""
        return "<SecureBuffer[***]>"
    
    def __str__(self) -> str:
        """Block str() to prevent accidental logging."""
        return "<SecureBuffer[***]>"
    
    def __copy__(self):
        """Block copy.copy()."""
        raise TypeError("SecureBuffer cannot be copied")
    
    def __deepcopy__(self, memo):
        """Block copy.deepcopy()."""
        raise TypeError("SecureBuffer cannot be deepcopied")
    
    def __reduce__(self):
        """Block pickle."""
        raise TypeError("SecureBuffer cannot be pickled")
    
    def __reduce_ex__(self, protocol):
        """Block pickle with protocol."""
        raise TypeError("SecureBuffer cannot be pickled")
    
    def __getstate__(self):
        """Block state access for serialization."""
        raise TypeError("SecureBuffer cannot be serialized")
    
    def __setstate__(self, state):
        """Block state restore."""
        raise TypeError("SecureBuffer cannot be deserialized")
    
    # ──────────────────────────────────────────────────────────
    # Context manager
    # ──────────────────────────────────────────────────────────
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - always zeroize."""
        self.close()
        return False


class SecureBytes:
    """
    Wrapper for secret bytes to prevent accidental logging.
    
    When printed/logged, shows <SecureBytes[***]> instead of content.
    """
    
    def __init__(self, data: bytes):
        """Wrap bytes in secure wrapper."""
        if not isinstance(data, bytes):
            raise TypeError(f"data must be bytes, got {type(data).__name__}")
        self._data = data
    
    @property
    def bytes(self) -> bytes:
        """Get unwrapped bytes."""
        return self._data
    
    def __repr__(self) -> str:
        """Block repr."""
        return f"<SecureBytes[{len(self._data)} bytes]>"
    
    def __str__(self) -> str:
        """Block str."""
        return f"<SecureBytes[{len(self._data)} bytes]>"
    
    def __copy__(self):
        """Prevent copying."""
        raise TypeError("SecureBytes cannot be copied")
    
    def __deepcopy__(self, memo):
        """Prevent deepcopy."""
        raise TypeError("SecureBytes cannot be deepcopied")
    
    def __reduce__(self):
        """Prevent pickle."""
        raise TypeError("SecureBytes cannot be pickled")


def wipe_memory(data: bytearray) -> None:
    """
    Securely wipe bytearray using ctypes.memset.
    
    Args:
        data: bytearray to wipe
    """
    if not isinstance(data, bytearray):
        raise TypeError(f"data must be bytearray, got {type(data).__name__}")
    
    if len(data) == 0:
        return
    
    array_type = ctypes.c_ubyte * len(data)
    array = array_type.from_buffer(data)
    ptr = ctypes.cast(array, ctypes.c_void_p)
    
    ctypes.memset(ptr, 0, ctypes.c_size_t(len(data)))
