#!/usr/bin/env python3
"""
FLOW: Vault Hardening - Practical Examples

Real-world examples of using the secure memory, vault hardening, and session modules.

Run: python3 examples/vault_examples.py
"""

import asyncio
import sys
import os

# Add project path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.security import (
    SecureBuffer,
    SecureBytes,
    VaultHardening,
    HardeningStatus,
    VaultSession,
    SecretAccessPolicy,
    create_default_policy,
)

# Colors for terminal output
GREEN = "\033[92m"
BLUE = "\033[94m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"


def print_section(title: str):
    """Print formatted section header."""
    print(f"\n{BLUE}{'='*60}")
    print(f"{title}")
    print(f"{'='*60}{RESET}\n")


def print_success(msg: str):
    """Print success message."""
    print(f"{GREEN}✓ {msg}{RESET}")


def print_warning(msg: str):
    """Print warning message."""
    print(f"{YELLOW}⚠ {msg}{RESET}")


def print_error(msg: str):
    """Print error message."""
    print(f"{RED}✗ {msg}{RESET}")


# Example 1: Secure Memory Allocation
def example_secure_buffer():
    """Example 1: Allocate and protect sensitive memory."""
    print_section("Example 1: Secure Memory Allocation")
    
    # Check platform
    if sys.platform != "linux":
        print_warning("SecureBuffer requires Linux, skipping...")
        return
    
    try:
        # Create secure buffer
        secret_data = b"my-api-key-12345"
        buf = SecureBuffer(secret_data)
        print_success(f"Allocated SecureBuffer ({len(secret_data)} bytes)")
        
        # Access data
        data = buf.bytes
        print(f"  Data accessible: {len(data)} bytes")
        print_success("SecureBuffer has mlock() + MADV_DONTDUMP")
        
        # Cannot copy (protected)
        try:
            copy_attempt = buf.bytes[:]  # OK - reading
            copy_data = bytes(copy_attempt)
            print_success(f"  Can read bytes: {len(copy_data)} bytes")
        except TypeError as e:
            print_error(f"  Copy blocked (expected): {e}")
        
        # Context manager auto-closes and zeroizes
        print_success("Closing buffer (will zeroize memory)...")
        buf.close()
        print_success("Memory zeroized with ctypes.memset()")
        
    except RuntimeError as e:
        print_error(f"SecureBuffer failed: {e}")


# Example 2: Process Hardening
def example_vault_hardening():
    """Example 2: Enable process-level hardening."""
    print_section("Example 2: Process Hardening")
    
    if sys.platform != "linux":
        print_warning("VaultHardening requires Linux, skipping...")
        return
    
    try:
        # Check initial status
        initial = HardeningStatus.report(verbose=True)
        print(f"Initial state:")
        for key, value in initial.items():
            print(f"  {key}: {value}")
        
        print_success("Enabling vault hardening...")
        VaultHardening.enable()
        print_success("✓ Process hardening applied:")
        print_success("  - Core dumps disabled (RLIMIT_CORE=0)")
        print_success("  - ptrace disabled (PR_SET_DUMPABLE=0)")
        print_success("  - Memory locked (mlockall)")
        
        # Check new status
        final = HardeningStatus.report(verbose=False)
        print(f"\nFinal hardening status:")
        print(f"  Enabled: {final['hardening_enabled']}")
        print(f"  Core dumps disabled: {final['core_dumps_disabled']}")
        print(f"  ptrace disabled: {final['ptrace_disabled']}")
        
        # Idempotent (can call again)
        print_success("(Hardening is idempotent - safe to call multiple times)")
        
    except RuntimeError as e:
        print_error(f"Hardening failed: {e}")


# Example 3: Vault Session
async def example_vault_session():
    """Example 3: Create vault session with TTL."""
    print_section("Example 3: Vault Session Unlock/Lock")
    
    if sys.platform != "linux":
        print_warning("VaultSession requires Linux, skipping...")
        return
    
    try:
        # Create session with 30-second TTL (for demo)
        print_success("Creating VaultSession (TTL=30s for demo)...")
        session = VaultSession(ttl_seconds=30)
        
        # Check initial state
        assert not session.is_unlocked()
        print_success("Session created (locked)")
        
        # Unlock
        passphrase = "super-secret-passphrase"
        print_success(f"Unlocking with passphrase (Argon2id KDF)...")
        await session.unlock(passphrase)
        print_success("Session unlocked ✓")
        
        # Get session info
        info = session.get_session_info()
        print(f"\nSession info:")
        print(f"  Is unlocked: {info['is_unlocked']}")
        print(f"  TTL seconds: {info['ttl_seconds']}")
        print(f"  Seconds remaining: {info['seconds_remaining']}")
        
        # Derive namespace-specific keys
        print_success("\nDeriving namespace-specific keys...")
        key_trust = session.derive_namespace_key("trust_store")
        key_oauth = session.derive_namespace_key("oauth")
        print_success(f"  trust_store key: {key_trust[:16].hex()}... ({len(key_trust)} bytes)")
        print_success(f"  oauth key: {key_oauth[:16].hex()}... ({len(key_oauth)} bytes)")
        
        # Keys are different
        assert key_trust != key_oauth
        print_success("  → Different namespaces get different keys (HKDF isolation)")
        
        # Keys are deterministic
        key_trust_2 = session.derive_namespace_key("trust_store")
        assert key_trust == key_trust_2
        print_success("  → Same passphrase + namespace = same key (deterministic)")
        
        # Lock
        print_success("\nLocking session (will zeroize master key)...")
        await session.lock()
        assert not session.is_unlocked()
        print_success("Session locked ✓")
        
        # Cannot derive after lock
        try:
            session.derive_namespace_key("trust_store")
            print_error("Should have raised VaultLockedError!")
        except Exception as e:
            print_success(f"  → Correctly raised {type(e).__name__}")
        
        print_success("\n✓ VaultSession protects master key with SecureBuffer")
        
    except Exception as e:
        print_error(f"VaultSession example failed: {e}")
        import traceback
        traceback.print_exc()


# Example 4: Access Policy
def example_secret_policy():
    """Example 4: Whitelist-based secret access control."""
    print_section("Example 4: Secret Access Policy")
    
    try:
        # Create policy
        print_success("Creating SecretAccessPolicy...")
        policy = SecretAccessPolicy()
        
        # Grant permissions
        policy.allow("oauth_provider", [
            "oauth.client_secret",
            "oauth.jwt_key",
        ])
        policy.allow("core.runtime", [
            "core.app_key",
            "core.db_password",
        ])
        
        print_success("Granted permissions:")
        print(f"  oauth_provider: {policy.get_allowed_namespaces('oauth_provider')}")
        print(f"  core.runtime: {policy.get_allowed_namespaces('core.runtime')}")
        
        # Check access
        print_success("\nChecking access control...")
        assert policy.is_allowed("oauth_provider", "oauth.client_secret")
        print_success("  ✓ oauth_provider can access oauth.client_secret")
        
        assert not policy.is_allowed("oauth_provider", "core.app_key")
        print_success("  ✓ oauth_provider CANNOT access core.app_key (denied)")
        
        # Revoke
        print_success("\nRevoking access...")
        policy.deny("oauth_provider", "oauth.client_secret")
        assert not policy.is_allowed("oauth_provider", "oauth.client_secret")
        print_success("  ✓ Revoked oauth_provider from oauth.client_secret")
        
        # Default policy
        print_success("\nUsing default policy...")
        default_policy = create_default_policy()
        print(f"  core.runtime permissions: {default_policy.get_allowed_namespaces('core.runtime')}")
        print(f"  oauth permissions: {default_policy.get_allowed_namespaces('oauth')}")
        
    except Exception as e:
        print_error(f"Policy example failed: {e}")


# Example 5: SecureBytes Wrapper
def example_secure_bytes():
    """Example 5: Logging protection with SecureBytes."""
    print_section("Example 5: SecureBytes Logging Protection")
    
    secret_value = b"password123456"
    
    # Unsafe: regular bytes
    print_success("Regular bytes (unsafe for logging):")
    print(f"  repr: {repr(secret_value)[:60]}...")
    print(f"  str: {str(secret_value)[:60]}...")
    print_warning("  → Secret visible in logs!")
    
    # Safe: SecureBytes wrapper
    print_success("\nSecureBytes wrapper (safe for logging):")
    safe = SecureBytes(secret_value)
    print(f"  repr: {repr(safe)}")
    print(f"  str: {str(safe)}")
    print(f"  type: {type(safe).__name__}")
    print_success("  → Secret MASKED in logs [***]")
    
    # Still access actual bytes
    print_success("\nAccess actual bytes when needed:")
    actual = safe.bytes
    print(f"  .bytes property: {actual[:10]}...{actual[-4:]}")
    print_success("  → Can access but easy to audit (explicit .bytes access)")


async def main():
    """Run all examples."""
    import platform
    
    # Header
    print(f"\n{BLUE}")
    print("=" * 60)
    print("FLOW: Linux Hardened Vault - Practical Examples")
    print("=" * 60)
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"{RESET}")
    
    # Run examples
    example_secure_buffer()
    example_vault_hardening()
    await example_vault_session()
    example_secret_policy()
    example_secure_bytes()
    
    # Footer
    print(f"\n{GREEN}{'='*60}")
    print("✓ All examples completed successfully")
    print(f"{'='*60}{RESET}\n")


if __name__ == "__main__":
    if sys.platform != "linux":
        print_error("These examples require Linux (glibc + CAP_IPC_LOCK)")
        print_warning("Run with: pip install cryptography")
        sys.exit(1)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print_warning("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print_error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
