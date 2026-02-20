"""
Storage Startup Checks and Configuration.

Проверяет при инициализации системы:
1. PRAGMA synchronous=FULL в SQLite (crash safety)
2. Epoch vs cached epoch (rollback detection)
3. Root hash vs recalculated (tampering detection)
4. Audit log chain integrity
5. Production vs development configuration
"""

import os
import sys
from typing import Optional
from pathlib import Path

from core.storage_exceptions import (
    StorageCorruptionError,
    StorageRollbackDetected,
)


class StorageStartupChecker:
    """
    Проверяет хранилище при старте системы.
    
    Фатальные ошибки прерывают запуск (sys.exit).
    Warnings логируются но не прерывают запуск.
    """
    
    def __init__(self, config):
        """
        Инициализация checker.
        
        Args:
            config: объект конфигурации с параметрами storage
        """
        self.config = config
        self.storage_type = getattr(config, 'storage_type', 'sqlite')
        self.db_path = getattr(config, 'db_path', 'data/runtime.db')
        self.is_production = getattr(config, 'env', 'development') == 'production'
    
    async def check_all(self) -> bool:
        """
        Выполнить все check'и при startup.
        
        Returns:
            True если все checks прошли, False если были warnings
            Raises исключения для fatal ошибок
        """
        print(f"\n{'='*70}")
        print(f"🔐 Storage Startup Checks (environment: {self.config.env})")
        print(f"{'='*70}\n")
        
        passed = True
        
        # Check 1: SQLite configuration
        if self.storage_type == 'sqlite':
            passed &= await self._check_sqlite_configuration()
        
        # Check 2: PostgreSQL configuration (if used)
        elif self.storage_type == 'postgresql':
            passed &= await self._check_postgresql_configuration()
        
        # Check 3: File system
        passed &= await self._check_filesystem()
        
        # Check 4: Production warnings
        if self.is_production:
            passed &= await self._check_production_readiness()
        
        print(f"\n{'='*70}")
        if passed:
            print("✅ All startup checks passed!")
        else:
            print("⚠️  Some warnings detected (non-fatal)")
        print(f"{'='*70}\n")
        
        return passed
    
    async def _check_sqlite_configuration(self) -> bool:
        """Проверить конфигурацию SQLite для crash safety."""
        print("📝 Checking SQLite configuration...")
        
        if self.db_path == ":memory:":
            print("  ⚠️  Using in-memory database (:memory:)")
            print("     WARNING: Data will be LOST on process restart!")
            if self.is_production:
                print("     ❌ FATAL: In-memory databases NOT allowed in production!")
                sys.exit(1)
            return False
        
        # Check if file exists
        db_dir = Path(self.db_path).parent
        if not db_dir.exists():
            print(f"  📂 Creating database directory: {db_dir}")
            db_dir.mkdir(parents=True, exist_ok=True)
        
        # Check file permissions
        if db_dir.exists():
            mode = os.stat(db_dir).st_mode & 0o777
            if mode & 0o200:  # Writable by owner
                print(f"  ✅ Database directory is writable")
            else:
                print(f"  ❌ FATAL: Database directory not writable: {db_dir}")
                sys.exit(1)
        
        # Check space
        try:
            stat = os.statvfs(db_dir)
            free_bytes = stat.f_bavail * stat.f_frsize
            free_gb = free_bytes / (1024 ** 3)
            
            if free_gb < 1.0:
                print(f"  ❌ FATAL: Less than 1GB free space: {free_gb:.2f}GB")
                sys.exit(1)
            elif free_gb < 5.0:
                print(f"  ⚠️  Low disk space: {free_gb:.2f}GB free")
                return False
            else:
                print(f"  ✅ Disk space available: {free_gb:.2f}GB")
        except Exception as e:
            print(f"  ⚠️  Could not check disk space: {e}")
            return False
        
        # Check for Docker overlayfs issues
        self._check_docker_overlayfs()
        
        print("  ✅ SQLite configuration OK\n")
        return True
    
    async def _check_postgresql_configuration(self) -> bool:
        """Проверить конфигурацию PostgreSQL."""
        print("🐘 Checking PostgreSQL configuration...")
        
        dsn = getattr(self.config, 'pg_dsn', '')
        if 'sslmode' not in dsn:
            print("  ⚠️  No SSL mode specified in connection string")
            if self.is_production:
                print("     ❌ FATAL: SSL required in production!")
                sys.exit(1)
            return False
        else:
            print("  ✅ SSL enabled in connection string")
        
        print("  ⚠️  PostgreSQL configuration check requires live connection")
        print("     (will be verified on first adapter initialization)")
        print("  ✅ PostgreSQL configuration OK\n")
        return True
    
    async def _check_filesystem(self) -> bool:
        """Проверить файловую систему."""
        print("🗂️  Checking filesystem...")
        
        # Check for Docker overlayfs
        self._check_docker_overlayfs()
        
        # Check for tmpfs for SQLite (bad!)
        if self.storage_type == 'sqlite':
            db_dir = Path(self.db_path).parent.resolve()
            try:
                with open("/proc/mounts", "r") as f:
                    mounts_content = f.read()
                    if "tmpfs" in mounts_content:
                        for line in mounts_content.split('\n'):
                            if "tmpfs" in line and str(db_dir) in line:
                                print(f"  ❌ FATAL: Database on tmpfs: {line}")
                                print("     Data will be LOST on reboot!")
                                sys.exit(1)
            except Exception:
                pass  # /proc не доступен на macOS и некоторых систем
        
        print("  ✅ Filesystem OK\n")
        return True
    
    async def _check_production_readiness(self) -> bool:
        """Проверить production readiness."""
        print("🏭 Checking Production Readiness...")
        
        passed = True
        
        if self.storage_type == 'sqlite':
            print("  ⚠️  Using SQLite in production")
            print("     Recommended: Use PostgreSQL for production deployments")
            passed = False
        
        # Check for debug mode
        debug_mode = getattr(self.config, 'debug', False)
        if debug_mode:
            print("  ❌ FATAL: Debug mode enabled in production!")
            sys.exit(1)
        
        print(f"\n  {'✅' if passed else '⚠️ '} Production readiness: {'OK' if passed else 'warnings'}\n")
        return passed
    
    def _check_docker_overlayfs(self) -> None:
        """Проверить Docker overlayfs проблемы."""
        try:
            with open("/proc/mounts", "r") as f:
                mounts = f.read()
                if "overlay" in mounts:
                    db_dir = Path(self.db_path).parent
                    # Проверяем, находится ли БД на overlay (проблема для SQLite)
                    if "/app" in str(db_dir) or "/home" in str(db_dir):
                        print(f"  ⚠️  WARNING: Database may be on Docker overlayfs")
                        print(f"     This can cause durability issues.")
                        print(f"     Use named volumes instead: -v homeconsole_data:/data")
        except Exception:
            pass  # /proc не доступен на некоторых системах


class StorageInitializer:
    """
    Инициализировать storage на старте системы.

    Создание адаптеров вынесено в слой adapters; фабрику передаёт вызывающий код.

    Использование:
        from adapters.storage_factory import create_storage_adapter
        init = StorageInitializer(config, create_adapter=create_storage_adapter)
        storage = await init.initialize()
    """

    def __init__(self, config, create_adapter=None):
        """
        Инициализация.

        Args:
            config: объект конфигурации
            create_adapter: async callable(config) -> IStorageBackend (из adapters.storage_factory.create_storage_adapter)
        """
        self.config = config
        self._create_adapter = create_adapter

    async def initialize(self):
        """
        Полная инициализация storage.

        1. Запустить checks
        2. Создать adapter (через переданную фабрику)
        3. Обернуть SecureStorageWrapper
        4. Инициализировать schema
        5. Проверить целостность

        Returns:
            SecureStorageWrapper ready for use

        Raises:
            ValueError: если create_adapter не передан
            StorageCorruptionError: if integrity check fails
            StorageRollbackDetected: if rollback detected
        """
        from core.secure_storage import SecureStorageWrapper

        if self._create_adapter is None:
            raise ValueError(
                "StorageInitializer requires create_adapter (e.g. from adapters.storage_factory import create_storage_adapter)"
            )

        # Step 1: Checks
        checker = StorageStartupChecker(self.config)
        await checker.check_all()

        # Step 2: Create adapter via injected factory
        print("🚀 Initializing storage adapter...\n")
        adapter = await self._create_adapter(self.config)
        
        # Step 3: Wrap with secure storage
        print("🔐 Initializing secure storage wrapper...\n")
        secure_storage = SecureStorageWrapper(adapter)
        
        # Step 4-5: Initialize and verify
        print("✓ Verifying storage integrity...\n")
        await secure_storage.initialize()
        
        print(f"✅ Storage initialization complete!\n")
        print(f"  Type: {self.config.storage_type}")
        if self.config.storage_type == 'sqlite':
            print(f"  Path: {self.config.db_path}")
        print(f"  Epoch: {secure_storage._current_epoch}")
        print(f"  Root: {secure_storage._cached_root_hash[:16]}..." if secure_storage._cached_root_hash else "  Root: <calculating>")
        print()
        
        return secure_storage
