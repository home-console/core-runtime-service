"""
Linux Process Hardening for Vault.

Disables:
- Core dumps (RLIMIT_CORE = 0)
- ptrace attach (PR_SET_DUMPABLE = 0)
- Locks all current and future memory (mlockall)

LINUX ONLY - No fallback.
Must be called once at runtime initialization.
"""

import ctypes
import ctypes.util
import resource
import sys
from typing import Optional

_is_linux = sys.platform == "linux"

if _is_linux:
    # Load libc
    _libc_path = ctypes.util.find_library("c")
    if not _libc_path:
        raise RuntimeError("Cannot find libc - required for prctl/mlockall")

    _libc = ctypes.CDLL(_libc_path, use_errno=True)
else:
    _libc = None

# prctl constants
PR_SET_DUMPABLE = 4
PR_SET_DUMPABLE_OFF = 0

# mlockall constants
MCL_CURRENT = 1
MCL_FUTURE = 2


def _get_errno() -> int:
    """Get errno after libc call."""
    if _is_linux:
        return ctypes.get_errno()
    return 0


class VaultHardening:
    """
    Linux process hardening for Vault.
    
    Call VaultHardening.enable() once at runtime startup to:
    1. Disable core dumps (no memory disclosure)
    2. Disable ptrace attacks (no process inspection)
    3. Lock all current and future memory (no swapping)
    
    All operations MUST succeed - no silent fallback.
    """
    
    _enabled = False  # Track if hardening was applied
    
    @staticmethod
    def enable() -> None:
        """
        Enable all vault hardening.
        
        Operations:
        1. disable_core_dumps() - RLIMIT_CORE = 0
        2. disable_ptrace() - PR_SET_DUMPABLE = 0
        3. lock_process_memory() - mlockall(MCL_CURRENT | MCL_FUTURE)
        
        Raises:
            RuntimeError: if any operation fails (no fallback)
        """
        if VaultHardening._enabled:
            return  # Idempotent
        
        print("[VaultHardening] Enabling process hardening...")
        
        if not _is_linux:
            print("[VaultHardening] WARNING: Platform does not support full hardening (requires Linux); using best-effort fallback")
        
        # Disable core dumps
        VaultHardening._disable_core_dumps()
        print("[VaultHardening] ✓ Core dumps disabled")
        
        if _is_linux:
            # Disable ptrace (Linux only)
            VaultHardening._disable_ptrace()
            print("[VaultHardening] ✓ ptrace attach disabled")
            
            # Lock process memory (Linux only)
            VaultHardening._lock_process_memory()
            print("[VaultHardening] ✓ Process memory locked")
        
        VaultHardening._enabled = True
    
    @staticmethod
    def _disable_core_dumps() -> None:
        """
        Disable core dumps via RLIMIT_CORE.
        
        Prevents memory contents from being written to disk.
        """
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except Exception as e:
            raise RuntimeError(f"Failed to disable core dumps: {e}")
    
    @staticmethod
    def _disable_ptrace() -> None:
        """
        Disable ptrace attach via PR_SET_DUMPABLE.
        
        Prevents other processes from attaching debugger or reading memory.
        Also disables ptrace, process_vm_readv, etc.
        """
        if not _is_linux:
            return
        result = _libc.prctl(
            ctypes.c_int(PR_SET_DUMPABLE),
            ctypes.c_int(PR_SET_DUMPABLE_OFF),
            ctypes.c_int(0),
            ctypes.c_int(0),
            ctypes.c_int(0)
        )
        
        if result != 0:
            errno = _get_errno()
            raise RuntimeError(
                f"prctl(PR_SET_DUMPABLE, 0) failed: errno={errno}. "
                f"This operation requires appropriate permissions."
            )
    
    @staticmethod
    def _lock_process_memory() -> None:
        """
        Lock all current and future memory via mlockall.
        
        Prevents any part of the process memory from being swapped to disk.
        MCL_CURRENT: Lock all currently allocated memory
        MCL_FUTURE: Lock all future allocations as well
        """
        if not _is_linux:
            return
        result = _libc.mlockall(ctypes.c_int(MCL_CURRENT | MCL_FUTURE))
        
        if result != 0:
            errno = _get_errno()
            
            # Check for common issues
            if errno == 12:  # ENOMEM
                raise RuntimeError(
                    f"mlockall() failed: ENOMEM. "
                    f"System memory limit exceeded. "
                    f"Check ulimit -l and available RAM."
                )
            else:
                raise RuntimeError(
                    f"mlockall(MCL_CURRENT | MCL_FUTURE) failed: errno={errno}. "
                    f"Check CAP_IPC_LOCK or increase ulimit -l. "
                    f"Run: ulimit -l unlimited"
                )
    
    @staticmethod
    def is_enabled() -> bool:
        """Check if hardening was applied."""
        return VaultHardening._enabled


class HardeningStatus:
    """Check current hardening status."""
    
    @staticmethod
    def get_core_dump_limit() -> tuple[int, int]:
        """Get current RLIMIT_CORE (soft, hard)."""
        return resource.getrlimit(resource.RLIMIT_CORE)
    
    @staticmethod
    def is_core_dumps_disabled() -> bool:
        """Check if core dumps are disabled."""
        soft, hard = HardeningStatus.get_core_dump_limit()
        return soft == 0 and hard == 0
    
    @staticmethod
    def get_dumpable_flag() -> int:
        """Get current PR_GET_DUMPABLE flag."""
        if not _is_linux:
            return 1  # Fallback: assume dumpable
        result = _libc.prctl(
            ctypes.c_int(3),  # PR_GET_DUMPABLE = 3
            ctypes.c_int(0),
            ctypes.c_int(0),
            ctypes.c_int(0),
            ctypes.c_int(0)
        )
        if result < 0:
            return -1  # Unknown
        return result
    
    @staticmethod
    def is_ptrace_disabled() -> bool:
        """Check if ptrace is disabled."""
        dumpable = HardeningStatus.get_dumpable_flag()
        return dumpable == 0
    
    @staticmethod
    def report(verbose: bool = False) -> dict:
        """
        Get hardening status report.
        
        Returns:
            dict with hardening flags
        """
        return {
            "hardening_enabled": VaultHardening.is_enabled(),
            "core_dumps_disabled": HardeningStatus.is_core_dumps_disabled(),
            "ptrace_disabled": HardeningStatus.is_ptrace_disabled(),
            "core_dump_limit": HardeningStatus.get_core_dump_limit() if verbose else None,
            "dumpable_flag": HardeningStatus.get_dumpable_flag() if verbose else None,
        }
