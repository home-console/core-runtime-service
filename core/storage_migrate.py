"""Compatibility exports for storage migration utilities.

Canonical implementation lives in modules.storage.migrate.
"""

from modules.storage.migrate import check_migration_status, migrate_to_dual_mode

__all__ = [
    "migrate_to_dual_mode",
    "check_migration_status",
]
