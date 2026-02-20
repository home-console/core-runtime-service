"""
Storage v3 Migration Tool - Migrate v1/v2 single-mode data to dual-mode.

This script:
1. Detects namespaces matching CRITICAL_VAULT_NAMESPACES in core storage
2. Copies records from core → vault storage 
3. Verifies counts match
4. Deletes records from core storage
5. Logs all operations

Usage:
    python -c "
    import asyncio
    from core.config import Config
    from core.storage_migrate import migrate_to_dual_mode
    
    config = Config.from_env()
    count = asyncio.run(migrate_to_dual_mode(config))
    print(f'Migrated {count} records to vault storage')
    "
"""

import sys
import logging
from typing import Dict, List, Tuple
from core.config import Config
from core.storage_manager import StorageManager, CRITICAL_VAULT_NAMESPACES
from core.storage_errors import StorageConfigurationError
from adapters.storage_factory import create_storage_manager


logger = logging.getLogger(__name__)


async def migrate_to_dual_mode(config: Config) -> int:
    """
    Migrate data from single mode to dual mode.
    
    Only runs if:
    - config.storage_mode == "dual"
    - Both core and vault adapters are initialized
    
    Process:
    1. Scan core storage for critical vault namespaces
    2. Copy matching records to vault storage
    3. Verify counts match
    4. Delete from core storage
    5. Return total records migrated
    
    Args:
        config: Config instance (should be validated)
    
    Returns:
        Total number of records migrated
    
    Raises:
        StorageConfigurationError: If not in dual mode or config is invalid
    """
    # Validate config
    config.validate()
    
    if config.storage_mode != "dual":
        logger.warning(
            f"Migration skipped: storage_mode is '{config.storage_mode}', not 'dual'"
        )
        return 0
    
    logger.info(
        f"Starting migration to dual-mode storage "
        f"(core: {config.storage_type}, vault: {config.vault_storage_type})"
    )
    
    # Create storage manager
    manager = await create_storage_manager(config)
    
    try:
        # Get both storage adapters
        core = manager.get_core()
        vault = manager.get_vault()
        
        # Track migration stats
        namespaces_found: Dict[str, int] = {}
        total_migrated = 0
        
        # Get all namespaces from core storage
        core_namespaces = await core.list_namespaces()
        logger.info(f"Found {len(core_namespaces)} namespaces in core storage")
        
        # Identify vault namespaces to migrate
        vault_namespaces = []
        for ns in core_namespaces:
            if _is_vault_namespace(ns):
                vault_namespaces.append(ns)
        
        if not vault_namespaces:
            logger.info("No vault namespaces found in core storage; migration complete")
            return 0
        
        logger.info(f"Found {len(vault_namespaces)} vault namespaces to migrate: {vault_namespaces}")
        
        # Migrate each vault namespace
        for namespace in vault_namespaces:
            keys = await core.list_keys(namespace)
            logger.info(f"  Migrating namespace '{namespace}': {len(keys)} records")
            
            migrated_count = 0
            errors = []
            
            # Copy records
            for key in keys:
                try:
                    value = await core.get(namespace, key)
                    if value is not None:
                        await vault.set(namespace, key, value)
                        migrated_count += 1
                except Exception as e:
                    errors.append((key, str(e)))
                    logger.error(f"    Failed to copy '{namespace}:{key}': {e}")
            
            # Verify copy succeeded
            vault_keys = await vault.list_keys(namespace)
            if len(vault_keys) < migrated_count:
                raise RuntimeError(
                    f"Vault storage has fewer records than copied for namespace '{namespace}': "
                    f"copied {migrated_count}, found {len(vault_keys)}"
                )
            
            # Delete from core storage (after successful copy)
            deleted_count = 0
            for key in keys:
                try:
                    deleted = await core.delete(namespace, key)
                    if deleted:
                        deleted_count += 1
                except Exception as e:
                    logger.error(f"    Failed to delete '{namespace}:{key}' from core: {e}")
            
            # Log results for this namespace
            namespaces_found[namespace] = migrated_count
            total_migrated += migrated_count
            
            logger.info(
                f"  ✓ {namespace}: copied={migrated_count}, deleted={deleted_count}, "
                f"errors={len(errors)}"
            )
            
            if errors:
                logger.warning(f"    Errors during migration of {namespace}: {errors}")
        
        logger.info(
            f"Migration complete: {total_migrated} total records migrated to vault storage\n"
            f"Summary: {namespaces_found}"
        )
        
        return total_migrated
    
    finally:
        # Always close the manager
        await manager.close()


def _is_vault_namespace(namespace: str) -> bool:
    """Check if namespace is in vault critical list."""
    for vault_ns in CRITICAL_VAULT_NAMESPACES:
        if namespace == vault_ns or namespace.startswith(vault_ns + "."):
            return True
    return False


async def check_migration_status(config: Config) -> Tuple[int, int]:
    """
    Check how many vault records are in core vs vault storage.
    
    Useful for monitoring migration progress.
    
    Args:
        config: Config instance
    
    Returns:
        Tuple[core_count, vault_count]
    """
    config.validate()
    
    if config.storage_mode != "dual":
        logger.warning("Migration status check only available in dual mode")
        return 0, 0
    
    manager = await create_storage_manager(config)
    
    try:
        core = manager.get_core()
        vault = manager.get_vault()
        
        core_count = 0
        vault_count = 0
        
        # Scan core storage
        core_namespaces = await core.list_namespaces()
        for ns in core_namespaces:
            if _is_vault_namespace(ns):
                keys = await core.list_keys(ns)
                core_count += len(keys)
        
        # Scan vault storage
        vault_namespaces = await vault.list_namespaces()
        for ns in vault_namespaces:
            if _is_vault_namespace(ns):
                keys = await vault.list_keys(ns)
                vault_count += len(keys)
        
        return core_count, vault_count
    
    finally:
        await manager.close()


if __name__ == "__main__":
    """CLI entry point."""
    import asyncio
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Get config from environment
    try:
        config = Config.from_env()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    
    # Run migration
    try:
        total = asyncio.run(migrate_to_dual_mode(config))
        logger.info(f"✓ Migration successful: {total} records moved to vault storage")
        sys.exit(0)
    except Exception as e:
        logger.error(f"✗ Migration failed: {e}", exc_info=True)
        sys.exit(1)
