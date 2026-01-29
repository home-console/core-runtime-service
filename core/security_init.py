"""
Security Initialization - проверка безопасности при старте runtime.

SECURITY P0: Runtime MUST fail-fast if critical security components not configured.

Этот модуль интегрируется в CoreRuntime startup для проверки:
- OAUTH_ENCRYPTION_KEY установлен
- CSRF_SECRET установлен  
- YANDEX_CLIENT_SECRET установлен (или warning)
- Все security компоненты доступны
"""

import os
import sys
from typing import Dict, List


def check_security_requirements() -> Dict[str, List[str]]:
    """
    Проверить требования безопасности.
    
    CRITICAL: Вызывается при старте runtime.
    System НЕ стартует без обязательных env variables.
    
    Returns:
        Dict с errors и warnings
        
    Raises:
        RuntimeError: If critical security requirements not met
    """
    errors = []
    warnings = []
    
    # P0: OAuth token encryption
    if not os.environ.get("OAUTH_ENCRYPTION_KEY"):
        errors.append(
            "OAUTH_ENCRYPTION_KEY not set - OAuth tokens WILL be stored in PLAINTEXT. "
            "Generate with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    
    # P0: CSRF protection
    if not os.environ.get("CSRF_SECRET"):
        errors.append(
            "CSRF_SECRET not set - Admin API vulnerable to CSRF attacks. "
            "Generate with: python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    
    # P1: OAuth client secrets
    if not os.environ.get("YANDEX_CLIENT_SECRET"):
        warnings.append(
            "YANDEX_CLIENT_SECRET not set - hardcoded secret will be used (INSECURE for production). "
            "Set YANDEX_CLIENT_SECRET env variable."
        )
    
    # Check Python dependencies
    try:
        import cryptography
    except ImportError:
        errors.append(
            "cryptography package not installed - token encryption unavailable. "
            "Install with: pip install cryptography"
        )
    
    return {
        "errors": errors,
        "warnings": warnings
    }


def print_security_banner(check_result: Dict[str, List[str]]) -> None:
    """
    Вывести security banner при старте.
    
    Args:
        check_result: Result from check_security_requirements()
    """
    errors = check_result.get("errors", [])
    warnings = check_result.get("warnings", [])
    
    if not errors and not warnings:
        print("✅ Security configuration: OK", file=sys.stderr)
        return
    
    print("\n" + "="*80, file=sys.stderr)
    print("🔒 SECURITY CONFIGURATION CHECK", file=sys.stderr)
    print("="*80 + "\n", file=sys.stderr)
    
    if errors:
        print("❌ ERRORS (system will NOT start):", file=sys.stderr)
        for i, error in enumerate(errors, 1):
            print(f"  {i}. {error}", file=sys.stderr)
        print("", file=sys.stderr)
    
    if warnings:
        print("⚠️  WARNINGS:", file=sys.stderr)
        for i, warning in enumerate(warnings, 1):
            print(f"  {i}. {warning}", file=sys.stderr)
        print("", file=sys.stderr)
    
    print("="*80 + "\n", file=sys.stderr)


def validate_or_fail() -> None:
    """
    Validate security configuration or fail.
    
    CRITICAL: Call this during runtime initialization.
    System will NOT start if requirements not met.
    
    Raises:
        SystemExit: If critical requirements not met
    """
    result = check_security_requirements()
    print_security_banner(result)
    
    if result["errors"]:
        print("❌ FATAL: Cannot start with security errors. Fix configuration and restart.", file=sys.stderr)
        sys.exit(1)


# Quick test when run as script
if __name__ == "__main__":
    try:
        validate_or_fail()
        print("✅ Security validation passed")
    except SystemExit:
        pass
