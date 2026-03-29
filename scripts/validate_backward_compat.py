"""
Backward Compatibility Validation for Storage v3

Validates:
1. Old storage adapter code continues to work without changes
2. New StorageManager code works in single mode
3. Dual mode introduces no regressions
4. Migration from single to dual mode works correctly
"""

import asyncio
import os
import sys
import tempfile

# Setup test environment
os.environ.setdefault("RUNTIME_LOG_FORMAT", "text")


async def test_backward_compat_old_adapter_api():
    """Test that old StorageAdapter API still works."""
    print("\n[TEST 1] Old StorageAdapter API")
    print("-" * 60)

    from core.adapters.sqlite_adapter import SQLiteAdapter

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # Old code pattern (still works!)
        adapter = SQLiteAdapter(db_path)
        await adapter.initialize_schema()

        # Test basic operations
        await adapter.set("app.config", "setting1", {"value": "test"})
        await adapter.set("secrets.store", "password", {"pwd": "secret"})

        value1 = await adapter.get("app.config", "setting1")
        value2 = await adapter.get("secrets.store", "password")

        assert value1 == {"value": "test"}, (
            f"Expected {{'value': 'test'}}, got {value1}"
        )
        assert value2 == {"pwd": "secret"}, (
            f"Expected {{'pwd': 'secret'}}, got {value2}"
        )

        # Test list operations
        keys = await adapter.list_keys("app.config")
        assert "setting1" in keys, f"Expected 'setting1' in keys, got {keys}"

        namespaces = await adapter.list_namespaces()
        assert "app.config" in namespaces, (
            f"Expected 'app.config' in namespaces, got {namespaces}"
        )

        # Test delete
        deleted = await adapter.delete("app.config", "setting1")
        assert deleted is True, f"Expected True, got {deleted}"

        deleted_again = await adapter.delete("app.config", "setting1")
        assert deleted_again is False, f"Expected False, got {deleted_again}"

        await adapter.close()

        print("✓ Old StorageAdapter API works without changes")
        return True

    except Exception as e:
        print(f"✗ Old StorageAdapter API failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


async def test_single_mode_storage_manager():
    """Test StorageManager in single mode (should work identically to old API)."""
    print("\n[TEST 2] StorageManager Single Mode")
    print("-" * 60)

    from core.adapters.sqlite_adapter import SQLiteAdapter
    from modules.storage.manager import StorageManager

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # New code pattern: StorageManager wrapping old adapter
        adapter = SQLiteAdapter(db_path)
        await adapter.initialize_schema()

        manager = StorageManager(core_storage=adapter, mode="single")

        # Test operations through manager
        await manager.set("app.config", "setting2", {"value": "test2"})
        await manager.set("secrets.store", "api_key", {"key": "secret"})

        value1 = await manager.get("app.config", "setting2")
        value2 = await manager.get("secrets.store", "api_key")

        assert value1 == {"value": "test2"}, (
            f"Expected {{'value': 'test2'}}, got {value1}"
        )
        assert value2 == {"key": "secret"}, (
            f"Expected {{'key': 'secret'}}, got {value2}"
        )

        # Test that both go to same storage
        assert manager.get_core() is adapter
        assert manager.get_vault() is adapter  # Single mode returns core for vault

        assert manager.mode == "single"
        assert manager.is_dual_mode is False

        await manager.close()

        print("✓ StorageManager single mode works correctly")
        return True

    except Exception as e:
        print(f"✗ StorageManager single mode failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


async def test_dual_mode_isolation():
    """Test that dual mode properly isolates core and vault storage."""
    print("\n[TEST 3] StorageManager Dual Mode Isolation")
    print("-" * 60)

    from core.adapters.sqlite_adapter import SQLiteAdapter
    from modules.storage.manager import StorageManager

    with tempfile.TemporaryDirectory() as tmpdir:
        core_path = os.path.join(tmpdir, "core.db")
        vault_path = os.path.join(tmpdir, "vault.db")

        try:
            # Create separate adapters
            core_adapter = SQLiteAdapter(core_path)
            await core_adapter.initialize_schema()

            vault_adapter = SQLiteAdapter(vault_path)
            await vault_adapter.initialize_schema()

            # Create dual-mode manager
            manager = StorageManager(
                core_storage=core_adapter, vault_storage=vault_adapter, mode="dual"
            )

            assert manager.mode == "dual"
            assert manager.is_dual_mode is True
            assert manager.get_core() is core_adapter
            assert manager.get_vault() is vault_adapter

            # Test namespace isolation: vault namespace goes to vault storage
            await manager.set("secrets.store", "password", {"pwd": "secret"})

            # Verify in vault only
            vault_pwd = await vault_adapter.get("secrets.store", "password")
            core_pwd = await core_adapter.get("secrets.store", "password")

            assert vault_pwd == {"pwd": "secret"}, (
                f"Expected secret in vault, got {vault_pwd}"
            )
            assert core_pwd is None, f"Expected None in core, got {core_pwd}"

            # Test core namespace goes to core storage
            await manager.set("app.config", "setting", {"val": "x"})

            core_setting = await core_adapter.get("app.config", "setting")
            vault_setting = await vault_adapter.get("app.config", "setting")

            assert core_setting == {"val": "x"}, (
                f"Expected setting in core, got {core_setting}"
            )
            assert vault_setting is None, f"Expected None in vault, got {vault_setting}"

            await manager.close()

            print("✓ Dual mode isolation works correctly")
            return True

        except Exception as e:
            print(f"✗ Dual mode isolation failed: {e}")
            import traceback

            traceback.print_exc()
            return False


async def test_config_backward_compat():
    """Test that Config still works with default single mode."""
    print("\n[TEST 4] Config Backward Compatibility")
    print("-" * 60)

    from core.config import Config

    try:
        # Old code: Config without storage_mode (should default to single)
        config = Config(
            storage_type="sqlite",
            db_path="data/test.db",
        )

        # Should have defaults
        assert config.storage_mode == "single", (
            f"Expected 'single', got {config.storage_mode}"
        )
        assert config.vault_storage_type is None
        assert config.vault_db_path is None

        # Should validate without errors
        config.validate()

        print("✓ Config backward compatible (defaults to single mode)")
        return True

    except Exception as e:
        print(f"✗ Config backward compat failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_factory_backward_compat():
    """Test that storage factory maintain backward compatibility."""
    print("\n[TEST 5] Storage Factory Backward Compatibility")
    print("-" * 60)

    from modules.storage.factory import (
        create_storage_adapter,
        create_storage_manager,
    )
    from core.config import Config

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        config = Config(
            storage_type="sqlite",
            db_path=db_path,
        )

        # Old API still works: create_storage_adapter
        adapter = await create_storage_adapter(config)
        assert adapter is not None
        await adapter.close()

        # New API: create_storage_manager
        manager = await create_storage_manager(config)
        assert manager is not None
        assert manager.mode == "single"
        await manager.close()

        print("✓ Storage factory backward compatible")
        return True

    except Exception as e:
        print(f"✗ Storage factory compat failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


async def test_single_to_dual_migration():
    """Test migration from single mode to dual mode."""
    print("\n[TEST 6] Migration Single → Dual Mode")
    print("-" * 60)

    from modules.storage.factory import create_storage_manager
    from core.config import Config
    from modules.storage.migrate import migrate_to_dual_mode

    with tempfile.TemporaryDirectory() as tmpdir:
        core_path = os.path.join(tmpdir, "core.db")
        vault_path = os.path.join(tmpdir, "vault.db")

        try:
            # flow: Create single-mode storage and populate with data
            single_config = Config(
                storage_type="sqlite",
                db_path=core_path,
            )

            single_manager = await create_storage_manager(single_config)

            # Add test data
            await single_manager.set("app.config", "feature", {"enabled": True})
            await single_manager.set("secrets.store", "api_key", {"key": "secret123"})
            await single_manager.set("oauth.tokens", "github", {"token": "ghp_xxx"})

            await single_manager.close()

            # flow: Switch to dual mode config
            dual_config = Config(
                storage_type="sqlite",
                db_path=core_path,
                storage_mode="dual",
                vault_storage_type="sqlite",
                vault_db_path=vault_path,
            )

            # flow: Run migration
            migrated_count = await migrate_to_dual_mode(dual_config)

            assert migrated_count == 2, (
                f"Expected 2 records migrated (secrets.store + oauth.tokens), got {migrated_count}"
            )

            # flow: Verify data is in dual mode
            dual_manager = await create_storage_manager(dual_config)

            # Vault records should be in vault storage
            vault_api_key = await dual_manager.get("secrets.store", "api_key")
            vault_token = await dual_manager.get("oauth.tokens", "github")
            assert vault_api_key == {"key": "secret123"}, (
                f"API key not in vault: {vault_api_key}"
            )
            assert vault_token == {"token": "ghp_xxx"}, (
                f"Token not in vault: {vault_token}"
            )

            # Core records should still be in core storage
            core_feature = await dual_manager.get("app.config", "feature")
            assert core_feature == {"enabled": True}, (
                f"Feature not in core: {core_feature}"
            )

            await dual_manager.close()

            print("✓ Migration from single to dual mode works correctly")
            return True

        except Exception as e:
            print(f"✗ Migration test failed: {e}")
            import traceback

            traceback.print_exc()
            return False


async def main():
    """Run all backward compatibility tests."""
    print("=" * 60)
    print("BACKWARD COMPATIBILITY VALIDATION")
    print("=" * 60)

    results = []

    # Run tests
    results.append(
        ("Old StorageAdapter API", await test_backward_compat_old_adapter_api())
    )
    results.append(
        ("StorageManager Single Mode", await test_single_mode_storage_manager())
    )
    results.append(("StorageManager Dual Mode", await test_dual_mode_isolation()))
    results.append(("Config Backward Compat", await test_config_backward_compat()))
    results.append(("Storage Factory Compat", await test_factory_backward_compat()))
    results.append(("Single→Dual Migration", await test_single_to_dual_migration()))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} passed")

    if passed == total:
        print("\n✓ All backward compatibility tests PASSED")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) FAILED")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
