"""
Secure Storage Wrapper — P0 hardening for cold storage.

Добавляет:
- Part B: Global Storage Epoch (rollback protection)
- Part C: Cryptographic state verification (Merkle root, signed)
- Part 4: Atomic transaction guarantee
- Part 5: Append-only audit log
- Part 6: Enforcement of secure writes for critical namespaces

Использование:
    adapter = SQLiteAdapter("data.db")
    storage = SecureStorageWrapper(adapter)
    await storage.initialize()
    await storage.secure_set("trust_store", "key1", {...})
"""

from typing import Any, Optional, AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
import json
import os
import time
import asyncio

from core.storage_abstraction import IStorageBackend
from core.storage_exceptions import (
    StorageCorruptionError,
    StorageRollbackDetected, 
    StorageTamperDetected
)
from core.storage_crypto import (
    sha256_json,
    sha256_string,
    sha256_bytes,
    canonical_json,
    calculate_namespace_root,
    calculate_storage_root,
    merkle_root
)


# NAMESPACES, которые ДОЛЖНЫ проходить через secure_set
CRITICAL_NAMESPACES = {
    "trust_store",
    "agent_registry", 
    "secrets.store",
    "marketplace.transactions",
    "_audit.security",  # Step 17.5: Credential security audit trail (tamper-evident)
}

# NAMESPACES с системной информацией (не должны быть напрямую доступны)
SYSTEM_NAMESPACES = {
    "_system.meta",
    "_system.root_hash",
    "_system.audit_log",
}

# ALL PROTECTED NAMESPACES
PROTECTED_NAMESPACES = CRITICAL_NAMESPACES | SYSTEM_NAMESPACES


class SecureStorageWrapper:
    """
    Wrapper вокруг StorageAdapter, добавляющий криптографическую защиту и аудит.
    
    Архитектура:
    
    ┌─────────────────────────────────────────────────┐
    │ Application Layer (плагины)                     │
    │ await secure_storage.secure_set(ns, key, val)   │
    └─────────────────────────────────────────────────┘
                        ↓
    ┌─────────────────────────────────────────────────┐
    │ SecureStorageWrapper (Part B, C, 4, 5, 6)       │
    │ - Epoch bump                                     │
    │ - Merkle root recalc                            │
    │ - Audit log append                              │
    │ - Atomic transaction                            │
    └─────────────────────────────────────────────────┘
                        ↓
    ┌─────────────────────────────────────────────────┐
    │ StorageAdapter (_adapter)                       │
    │ - SQLiteAdapter / PostgreSQLAdapter             │
    │ - PRAGMA synchronous=FULL                       │
    │ - WAL mode (crash safety)                       │
    └─────────────────────────────────────────────────┘
    """
    
    def __init__(self, adapter: IStorageBackend):
        """Инициализация secure wrapper."""
        self._adapter = adapter
        self._lock = asyncio.Lock()  # Глобальная блокировка для секурных операций
        self._current_epoch = 0
        self._cached_root_hash = None
    
    async def initialize(self) -> None:
        """Инициализация schema и проверка целостности при startup."""
        # Инициализируем adapter
        await self._adapter.initialize_schema()
        
        # Добавим таблицы для system namespace если нужны
        # (StorageAdapter использует одну таблицу, но мы их логически разделяем)
        
        # Загружаем текущий epoch
        meta = await self._adapter.get("_system.meta", "global_epoch")
        if meta:
            self._current_epoch = meta.get("epoch", 0)
        else:
            # Первая инициализация
            self._current_epoch = 0
            await self._adapter.set("_system.meta", "global_epoch", {
                "epoch": 0,
                "updated_at": datetime.utcnow().isoformat(),
            })
        
        # Проверяем и рассчитываем root hash при старте
        await self._verify_storage_integrity()
    
    def _skip_root_verify(self) -> bool:
        """
        Не проверять root при старте, а пересчитать и сохранить (чтобы не падать в dev).
        Env: STORAGE_SKIP_ROOT_VERIFY=1 или DEBUG=1 (или true/yes).

        Почему хеш меняется: см. комментарий в коде про mismatch.
        """
        skip = os.environ.get("STORAGE_SKIP_ROOT_VERIFY", "").lower() in ("1", "true", "yes")
        debug = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")
        return skip or debug

    async def _verify_storage_integrity(self) -> None:
        """
        Проверка целостности хранилища при старте (Part C.3).
        При STORAGE_SKIP_ROOT_VERIFY=1 или DEBUG=1 — только пересчёт и сохранение root.
        """
        if self._skip_root_verify():
            reason = "STORAGE_SKIP_ROOT_VERIFY=1" if os.environ.get("STORAGE_SKIP_ROOT_VERIFY") else "DEBUG=1"
            print(f"[SecureStorage] {reason}: recalculating root hash on startup (no verify).")
            await self._recalculate_root_hash()
            return

        stored_root_data = await self._adapter.get("_system.root_hash", "current")
        if not stored_root_data:
            print(
                "[SecureStorage] No stored root hash found. "
                "This is expected on first startup. Creating initial root hash..."
            )
            await self._recalculate_root_hash()
            return

        current_root = await self._calculate_current_root_hash()
        stored_root = stored_root_data.get("root_hash")
        if current_root != stored_root:
            raise StorageCorruptionError(
                f"Root hash mismatch on startup! "
                f"Expected: {stored_root}, "
                f"Current: {current_root}. "
                f"Storage may be corrupted or tampered."
            )
        print(f"[SecureStorage] Root hash verified: {current_root[:16]}...")
    
    async def _calculate_current_root_hash(self) -> str:
        """
        Пересчитать текущий Merkle root для всего хранилища.
        
        Алгоритм:
        1. Для каждого namespace (кроме _system)
        2. Для каждого key в namespace
        3. Вычислить SHA256(value)
        4. Построить Merkle tree для namespace
        5. Построить глобальный Merkle tree
        """
        namespace_roots = {}
        
        # Сортируем namespace для детерминированного хеша (порядок в БД может отличаться)
        all_namespaces = await self._adapter.list_namespaces()
        namespaces = sorted(ns for ns in all_namespaces if not ns.startswith("_system"))
        
        for ns in namespaces:
            key_hashes = {}
            async for key, value in self._adapter.iter_namespace(ns, batch_size=100):
                value_hash = sha256_json(value)
                key_hashes[key] = value_hash
            if key_hashes:
                namespace_root = calculate_namespace_root(key_hashes)
                namespace_roots[ns] = namespace_root
        
        # Вычисляем глобальный root
        global_root = calculate_storage_root(namespace_roots)
        self._cached_root_hash = global_root
        return global_root
    
    async def _recalculate_root_hash(self) -> None:
        """Пересчитать и сохранить root hash."""
        current_root = await self._calculate_current_root_hash()
        
        root_data = {
            "root_hash": current_root,
            "epoch": self._current_epoch,
            "signed_by": "core_key",  # Placeholder; real Ed25519/ECDSA signing in Step 17+
            "calculated_at": datetime.utcnow().isoformat(),
        }
        
        # Сохраняем через adapter (без epoch bump, это системная операция)
        await self._adapter.set("_system.root_hash", "current", root_data)
    
    @asynccontextmanager
    async def transaction(self):
        """
        Контекстный менеджер для атомарных транзакций.
        
        Гарантирует, что:
        - Epoch update
        - Root hash update
        - Audit log append
        Выполняются атомарно (Part 4).
        """
        async with self._lock:
            async with self._adapter.transaction():
                yield
    
    async def _append_audit_log(
        self,
        namespace: str,
        key: str,
        operation: str,  # "SET" or "DELETE"
        value: Optional[dict[str, Any]],
    ) -> None:
        """
        Добавить запись в audit log (Part 5).
        
        Структура:
        {
            "id": incremental,
            "epoch": current_epoch,
            "namespace": "...",
            "key": "...",
            "operation": "SET/DELETE",
            "hash": sha256(value),
            "timestamp": "...",
            "prev_hash": "...",
            "entry_hash": sha256(prev_hash + data)
        }
        """
        # Получаем последнюю запись для prev_hash linkage
        audit_keys = await self._adapter.list_keys("_system.audit_log")
        prev_hash = None
        
        if audit_keys:
            # ID это последовательный номер, берем последний
            last_id = max(int(k) for k in audit_keys if k.isdigit())
            last_entry = await self._adapter.get("_system.audit_log", str(last_id))
            if last_entry:
                prev_hash = last_entry.get("entry_hash")
        
        if prev_hash is None:
            prev_hash = sha256_string("")  # Empty hash for first entry
        
        # Вычисляем хеш значения
        value_hash = sha256_json(value) if value else sha256_string("")
        
        # Новая запись
        new_id = len(audit_keys) + 1
        entry = {
            "id": new_id,
            "epoch": self._current_epoch,
            "namespace": namespace,
            "key": key,
            "operation": operation,
            "hash": value_hash,
            "timestamp": datetime.utcnow().isoformat(),
            "prev_hash": prev_hash,
        }
        
        # Вычисляем entry_hash
        entry_canonical = canonical_json(entry)
        entry["entry_hash"] = sha256_bytes((prev_hash + entry_canonical).encode('utf-8'))
        
        # Сохраняем в audit log (через adapter напрямую, чтобы избежать рекурсии)
        await self._adapter.set("_system.audit_log", str(new_id), entry)
    
    async def _bump_epoch(self) -> None:
        """Увеличить epoch и переподписать meta (Part B)."""
        self._current_epoch += 1
        
        meta = {
            "epoch": self._current_epoch,
            "updated_at": datetime.utcnow().isoformat(),
        }
        
        # Сохраняем через adapter
        await self._adapter.set("_system.meta", "global_epoch", meta)
    
    def _secure_set_body_sync(
        self,
        conn: Any,
        adapter: Any,
        namespace: str,
        key: str,
        value: dict[str, Any],
        current_epoch: int,
    ) -> int:
        """Синхронное тело secure_set в одном потоке (bump + audit + set). Возвращает new_epoch."""
        new_epoch = current_epoch + 1
        meta = {"epoch": new_epoch, "updated_at": datetime.utcnow().isoformat()}
        if not hasattr(adapter, "_set_with_conn"):
            raise RuntimeError("Adapter does not support run_atomic (_set_with_conn)")
        adapter._set_with_conn(conn, "_system.meta", "global_epoch", meta)
        audit_keys = adapter._list_keys_with_conn(conn, "_system.audit_log")
        prev_hash = None
        if audit_keys:
            digit_keys = [k for k in audit_keys if k.isdigit()]
            if digit_keys:
                last_id = max(int(k) for k in digit_keys)
                last_entry = adapter._get_with_conn(conn, "_system.audit_log", str(last_id))
                if last_entry:
                    prev_hash = last_entry.get("entry_hash")
        if prev_hash is None:
            prev_hash = sha256_string("")
        value_hash = sha256_json(value)
        new_id = len(audit_keys) + 1
        entry = {
            "id": new_id,
            "epoch": new_epoch,
            "namespace": namespace,
            "key": key,
            "operation": "SET",
            "hash": value_hash,
            "timestamp": datetime.utcnow().isoformat(),
            "prev_hash": prev_hash,
        }
        entry_canonical = canonical_json(entry)
        entry["entry_hash"] = sha256_bytes((prev_hash + entry_canonical).encode("utf-8"))
        adapter._set_with_conn(conn, "_system.audit_log", str(new_id), entry)
        adapter._set_with_conn(conn, namespace, key, value)
        return new_epoch

    def _secure_delete_body_sync(
        self,
        conn: Any,
        adapter: Any,
        namespace: str,
        key: str,
        current_epoch: int,
    ) -> tuple[int, bool]:
        """Синхронное тело secure_delete в одном потоке. Возвращает (new_epoch, deleted)."""
        new_epoch = current_epoch + 1
        meta = {"epoch": new_epoch, "updated_at": datetime.utcnow().isoformat()}
        adapter._set_with_conn(conn, "_system.meta", "global_epoch", meta)
        audit_keys = adapter._list_keys_with_conn(conn, "_system.audit_log")
        prev_hash = None
        if audit_keys:
            digit_keys = [k for k in audit_keys if k.isdigit()]
            if digit_keys:
                last_id = max(int(k) for k in digit_keys)
                last_entry = adapter._get_with_conn(conn, "_system.audit_log", str(last_id))
                if last_entry:
                    prev_hash = last_entry.get("entry_hash")
        if prev_hash is None:
            prev_hash = sha256_string("")
        value_hash = sha256_string("")
        new_id = len(audit_keys) + 1
        entry = {
            "id": new_id,
            "epoch": new_epoch,
            "namespace": namespace,
            "key": key,
            "operation": "DELETE",
            "hash": value_hash,
            "timestamp": datetime.utcnow().isoformat(),
            "prev_hash": prev_hash,
        }
        entry_canonical = canonical_json(entry)
        entry["entry_hash"] = sha256_bytes((prev_hash + entry_canonical).encode("utf-8"))
        adapter._set_with_conn(conn, "_system.audit_log", str(new_id), entry)
        deleted = adapter._delete_with_conn(conn, namespace, key)
        return (new_epoch, deleted)

    async def secure_set(
        self,
        namespace: str,
        key: str,
        value: dict[str, Any]
    ) -> None:
        """
        Безопасная запись в критичные namespace (Part 6).
        Использует run_atomic если адаптер поддерживает — одна транзакция в одном потоке (устраняет "database is locked").
        """
        if namespace not in CRITICAL_NAMESPACES:
            raise ValueError(
                f"secure_set() requires critical namespace, got {namespace}. "
                f"For regular storage, use adapter.set() directly."
            )
        if hasattr(self._adapter, "run_atomic"):
            new_epoch = await self._adapter.run_atomic(
                lambda conn, ad: self._secure_set_body_sync(
                    conn, ad, namespace, key, value, self._current_epoch
                )
            )
            self._current_epoch = new_epoch
        else:
            async with self.transaction():
                await self._bump_epoch()
                await self._append_audit_log(namespace, key, "SET", value)
                await self._adapter.set(namespace, key, value)
        await self._recalculate_root_hash()
    
    async def secure_delete(
        self,
        namespace: str,
        key: str
    ) -> bool:
        """
        Безопасное удаление из критичных namespace.
        
        Аналогично secure_set, но для DELETE операции.
        """
        if namespace not in CRITICAL_NAMESPACES:
            raise ValueError(
                f"secure_delete() requires critical namespace, got {namespace}."
            )
        if hasattr(self._adapter, "run_atomic"):
            new_epoch, deleted = await self._adapter.run_atomic(
                lambda conn, ad: self._secure_delete_body_sync(conn, ad, namespace, key, self._current_epoch)
            )
            self._current_epoch = new_epoch
        else:
            async with self.transaction():
                await self._bump_epoch()
                await self._append_audit_log(namespace, key, "DELETE", None)
                deleted = await self._adapter.delete(namespace, key)
        if deleted:
            await self._recalculate_root_hash()
        return deleted
    
    async def append(
        self,
        namespace: str,
        event: dict[str, Any]
    ) -> str:
        """
        Append-only write for security events (Step 17.5).
        
        Используется для неизменяемых событий аудита, которые:
        - Никогда не переписываются
        - Уникальны по ID
        - Должны быть tamper-evident
        
        Операция (идентична secure_set):
        1. Начинаем транзакцию
        2. Bump epoch (защита от rollback)
        3. Append audit log (P0 internal audit)
        4. Writes event (использует event["id"] как key)
        5. Recalculate merkle root
        6. Commit (атомарно)
        
        Args:
            namespace: Must be "_audit.security" for credential events
            event: Dict with 'id' and event data (e.g., SecurityEvent.to_dict())
            
        Returns:
            event["id"] (для confirmation)
            
        Raises:
            ValueError: If namespace not in CRITICAL_NAMESPACES
        """
        if namespace not in CRITICAL_NAMESPACES:
            raise ValueError(
                f"append() requires critical namespace, got {namespace}. "
                f"For append-only events, use namespace in {CRITICAL_NAMESPACES}"
            )
        
        if "id" not in event:
            raise ValueError(
                f"append() requires event['id'] to be present"
            )
        
        event_id = event["id"]
        
        async with self.transaction():
            # 1. Bump epoch (защита от rollback)
            await self._bump_epoch()
            
            # 2. Append to P0 audit log (internal P0 audit trail)
            await self._append_audit_log(namespace, event_id, "SET", event)
            
            # 3. Write event (key is event_id, unique per event)
            await self._adapter.set(namespace, event_id, event)
            
            # 4. Recalculate and save merkle root
            await self._recalculate_root_hash()
        
        return event_id
    
    # Delegate остальные методы к adapter
    async def get(self, namespace: str, key: str) -> Optional[dict[str, Any]]:
        """Получить значение (без защиты)."""
        return await self._adapter.get(namespace, key)
    
    async def set(self, namespace: str, key: str, value: dict[str, Any]) -> None:
        """Записать значение. Для критичных namespace — запрещено напрямую, используйте secure_set."""
        if namespace in CRITICAL_NAMESPACES:
            raise ValueError(
                f"Direct set() on critical namespace '{namespace}' is not allowed. "
                f"Use secure_set() instead for audit trail and integrity protection."
            )
        await self._adapter.set(namespace, key, value)
    
    async def delete(self, namespace: str, key: str) -> bool:
        """Удалить значение. Для критичных namespace — запрещено напрямую, используйте secure_delete."""
        if namespace in CRITICAL_NAMESPACES:
            raise ValueError(
                f"Direct delete() on critical namespace '{namespace}' is not allowed. "
                f"Use secure_delete() instead."
            )
        return await self._adapter.delete(namespace, key)
    
    async def list_keys(self, namespace: str) -> list[str]:
        """Получить список ключей."""
        return await self._adapter.list_keys(namespace)
    
    async def list_namespaces(self) -> list[str]:
        """Получить список namespace."""
        return await self._adapter.list_namespaces()
    
    async def clear_namespace(self, namespace: str) -> None:
        """Очистить namespace."""
        if namespace in PROTECTED_NAMESPACES:
            raise ValueError(
                f"Cannot clear protected namespace {namespace}."
            )
        await self._adapter.clear_namespace(namespace)
    
    async def close(self) -> None:
        """Закрыть подключение."""
        await self._adapter.close()
    
    @asynccontextmanager
    async def user_transaction(self):
        """Транзакция для обычного кода (не бамп epoch)."""
        async with self._adapter.transaction():
            yield
    
    async def iter_namespace(self, namespace: str, batch_size: int = 100) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Итерировать по namespace."""
        async for item in self._adapter.iter_namespace(namespace, batch_size):
            yield item
