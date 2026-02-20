"""
End-to-End Integration Test for Storage v3 Dual-Mode

Simulates a realistic runtime startup scenario:
1. Start in single mode (existing environment)
2. Populate with mixed data (core and vault)
3. Switch to dual mode configuration
4. Run migration
5. Verify data integrity and isolation
6. Perform dual-mode operations
"""

import asyncio
import sys
import os
import tempfile
import json
from pathlib import Path


async def e2e_test_dual_mode_workflow():
    """
    End-to-end test simulating real-world dual-mode adoption.
    """
    print("=" * 70)
    print("END-TO-END INTEGRATION TEST: Storage v3 Dual-Mode Workflow")
    print("=" * 70)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        core_path = os.path.join(tmpdir, "core.db")
        vault_path = os.path.join(tmpdir, "vault.db")
        
        try:
            # ========================================
            # PHASE 1: Initial Single-Mode Setup
            # ========================================
            print("\n[PHASE 1] Initial Single-Mode Setup")
            print("-" * 70)
            
            from core.config import Config
            from adapters.storage_factory import create_storage_manager
            
            single_config = Config(
                storage_type="sqlite",
                db_path=core_path,
                storage_mode="single",
            )
            
            # Validate config
            single_config.validate()
            print("✓ Single-mode config created and validated")
            
            # Create storage manager in single mode
            single_manager = await create_storage_manager(single_config)
            print(f"✓ StorageManager created (mode: {single_manager.mode})")
            
            # Simulate application startup with initial data
            test_data = {
                "app.config": {
                    "feature_flags": {"new_ui": True, "dark_mode": False},
                    "api_endpoints": {"github": "https://api.github.com"},
                    "db_pool_size": {"size": 10},
                },
                "secrets.store": {
                    "db_password": {"password": "super_secret_123"},
                    "api_key": {"key": "sk_test_abc123xyz"},
                },
                "oauth.tokens": {
                    "github": {"access_token": "ghp_xxx", "refresh_token": "ghr_yyy"},
                    "google": {"access_token": "ya29_zzz"},
                },
                "agent.private_keys": {
                    "ssh_key": {"type": "rsa", "key": "-----BEGIN PRIVATE KEY-----..."},
                },
                "runtime.state": {
                    "startup_count": {"count": 5},
                    "last_health_check": {"timestamp": "2024-01-15T10:30:00Z"},
                },
            }
            
            # Populate data
            for namespace, keys_data in test_data.items():
                for key, value in keys_data.items():
                    await single_manager.set(namespace, key, value)
                    print(f"  → {namespace}:{key}")
            
            print(f"✓ Populated {sum(len(d) for d in test_data.values())} test records")
            
            # Verify data is accessible
            feature_flags = await single_manager.get("app.config", "feature_flags")
            assert feature_flags is not None, "Failed to retrieve feature_flags"
            print(f"✓ Data retrieval works: {feature_flags}")
            
            await single_manager.close()
            print("✓ Single-mode manager closed")
            
            # ========================================
            # PHASE 2: Configuration Switch to Dual Mode
            # ========================================
            print("\n[PHASE 2] Configuration Switch to Dual Mode")
            print("-" * 70)
            
            dual_config = Config(
                storage_type="sqlite",
                db_path=core_path,
                storage_mode="dual",
                vault_storage_type="sqlite",
                vault_db_path=vault_path,
            )
            
            # Validate new config
            dual_config.validate()
            print("✓ Dual-mode config created and validated")
            print(f"  Core storage: {dual_config.storage_type} ({dual_config.db_path})")
            print(f"  Vault storage: {dual_config.vault_storage_type} ({dual_config.vault_db_path})")
            
            # ========================================
            # PHASE 3: Data Migration
            # ========================================
            print("\n[PHASE 3] Data Migration (Single → Dual)")
            print("-" * 70)
            
            from core.storage_migrate import migrate_to_dual_mode, check_migration_status
            
            # Check pre-migration status
            core_before, vault_before = await check_migration_status(dual_config)
            print(f"Pre-migration status: core={core_before}, vault={vault_before}")
            
            # Run migration
            migrated = await migrate_to_dual_mode(dual_config)
            print(f"✓ Migration completed: {migrated} records migrated to vault")
            
            # Check post-migration status
            core_after, vault_after = await check_migration_status(dual_config)
            print(f"Post-migration status: core={core_after}, vault={vault_after}")
            
            # Verify vault records were moved
            # secrets.store (2) + oauth.tokens (2) + agent.private_keys (1) = 5 records
            critical_vault_records = 5
            assert vault_after >= critical_vault_records, \
                f"Expected at least {critical_vault_records} in vault, got {vault_after}"
            print(f"✓ Vault storage contains critical secrets ({vault_after} records)")
            
            # ========================================
            # PHASE 4: Verify Dual-Mode Operation
            # ========================================
            print("\n[PHASE 4] Verify Dual-Mode Operations")
            print("-" * 70)
            
            dual_manager = await create_storage_manager(dual_config)
            print(f"✓ StorageManager created (mode: {dual_manager.mode})")
            
            # Verify core data still exists
            core_data = await dual_manager.get("app.config", "feature_flags")
            assert core_data == test_data["app.config"]["feature_flags"], \
                f"Core data corruption: {core_data}"
            print("✓ Core data integrity verified (app.config)")
            
            # Verify vault data is accessible but from vault storage
            secret_data = await dual_manager.get("secrets.store", "db_password")
            assert secret_data == test_data["secrets.store"]["db_password"], \
                f"Vault data corruption: {secret_data}"
            print("✓ Vault data integrity verified (secrets.store)")
            
            # Verify namespace isolation
            from core.storage_errors import NamespaceViolationError
            
            try:
                # Attempt to write vault namespace to core (should fail)
                await dual_manager.set(
                    "secrets.store",
                    "test_key",
                    {"test": "value"},
                    target="core"
                )
                print("✗ NamespaceViolationError NOT raised (BUG!)")
                return False
            except NamespaceViolationError:
                print("✓ Namespace enforcement working (vault namespace blocked from core)")
            
            # ========================================
            # PHASE 5: New Dual-Mode Operations
            # ========================================
            print("\n[PHASE 5] New Operations in Dual Mode")
            print("-" * 70)
            
            # Write new vault data (should auto-route to vault)
            new_secret = {"api_key": "sk_live_def789", "env": "production"}
            await dual_manager.set("secrets.store", "stripe_key", new_secret)
            print("✓ New vault data written (auto-routed to vault storage)")
            
            # Verify it's in vault only
            from adapters.sqlite_adapter import SQLiteAdapter
            
            core_adapter = SQLiteAdapter(core_path)
            vault_adapter = SQLiteAdapter(vault_path)
            
            core_stripe = await core_adapter.get("secrets.store", "stripe_key")
            vault_stripe = await vault_adapter.get("secrets.store", "stripe_key")
            
            assert core_stripe is None, "New vault data leaked to core storage!"
            assert vault_stripe == new_secret, "New vault data not in vault storage!"
            print("✓ New data properly isolated in vault storage")
            
            await core_adapter.close()
            await vault_adapter.close()
            
            # Write new core data
            new_config = {"batch_size": 100}
            await dual_manager.set("app.config", "performance", new_config)
            print("✓ New core data written (auto-routed to core storage)")
            
            # Verify retrieval
            retrieved = await dual_manager.get("app.config", "performance")
            assert retrieved == new_config, f"Config retrieval failed: {retrieved}"
            print("✓ New core data retrieved correctly")
            
            # ========================================
            # PHASE 6: Data Listing and Namespaces
            # ========================================
            print("\n[PHASE 6] Data Listing and Namespace Management")
            print("-" * 70)
            
            # List all namespaces
            namespaces = await dual_manager.list_namespaces()
            print(f"✓ Total namespaces: {len(namespaces)}")
            for ns in sorted(namespaces):
                keys = await dual_manager.list_keys(ns)
                print(f"  {ns}: {len(keys)} records")
            
            # Verify vault namespaces are in vault storage list
            vault_ns = dual_manager.get_vault_namespaces()
            print(f"✓ Critical vault namespaces: {vault_ns}")
            
            await dual_manager.close()
            
            # ========================================
            # SUMMARY
            # ========================================
            print("\n" + "=" * 70)
            print("END-TO-END TEST: PASSED ✓")
            print("=" * 70)
            print("\nWorkflow Summary:")
            print("  1. ✓ Single-mode setup with mixed data")
            print("  2. ✓ Configuration switch to dual-mode")
            print("  3. ✓ Data migration (vault records moved)")
            print("  4. ✓ Dual-mode operation (namespace isolation)")
            print("  5. ✓ New operations in dual mode")
            print("  6. ✓ Data integrity throughout")
            print("\nKey Achievements:")
            print(f"  • Migrated {migrated} records from core to vault storage")
            print(f"  • Vault storage contains {vault_after} records")
            print(f"  • Namespace enforcement prevents cross-storage writes")
            print("  • Backward compatibility maintained (single mode still works)")
            print("  • Data integrity verified end-to-end")
            
            return True
        
        except Exception as e:
            print(f"\n✗ TEST FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False


async def main():
    """Run the end-to-end test."""
    success = await e2e_test_dual_mode_workflow()
    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
