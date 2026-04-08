"""Security environment initialization check."""

import os
from typing import Dict, List


def check_security_env() -> Dict[str, List[str]]:
    """
    Check that required security environment variables are set.

    Returns:
        Dict with "errors" and "warnings" lists

    Raises:
        RuntimeError: If critical env variables missing
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not os.environ.get("OAUTH_ENCRYPTION_KEY"):
        errors.append("OAUTH_ENCRYPTION_KEY not set - tokens will be stored in plaintext")

    if not os.environ.get("CSRF_SECRET"):
        errors.append("CSRF_SECRET not set - admin API vulnerable to CSRF")

    yandex_client_secret = os.environ.get("YANDEX_CLIENT_SECRET")
    if not yandex_client_secret:
        warnings.append("YANDEX_CLIENT_SECRET not set - using hardcoded secret (INSECURE)")

    if errors:
        raise RuntimeError(
            f"Security environment check failed:\n"
            + "\n".join(f"  - {e}" for e in errors)
            + "\n\nSystem will NOT start without proper security configuration."
        )

    return {"errors": errors, "warnings": warnings}
