"""
Atomic Update Transaction Manager — crash-safe plugin updates.

Responsibilities:
- Atomic install/update with safe swap
- Rollback on failure + crash recovery
- State persistence
- Audit logging
"""

import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS

logger = logging.getLogger(__name__)


class TransactionState(str, Enum):
    """Transaction lifecycle states."""

    PREPARING = "preparing"  # Download step
    VALIDATING = "validating"  # Verification step
    STAGED = "staged"  # Ready for swap
    SWAPPING = "swapping"  # Atomic directory swap
    ACTIVATING = "activating"  # Starting plugin
    COMMITTED = "committed"  # Success
    ROLLED_BACK = "rolled_back"  # Rolled back
    FAILED = "failed"  # Permanent failure


class TransactionError(Exception):
    """Transaction operation failed."""

    pass


class RollbackError(Exception):
    """Rollback failed."""

    pass


@dataclass
class Transaction:
    """Single update transaction record."""

    plugin_name: str
    version: str
    action: str  # install, update, remove
    state: TransactionState
    start_time: str  # ISO format
    end_time: Optional[str] = None
    old_version: Optional[str] = None  # For updates
    backup_path: Optional[str] = None
    staging_path: Optional[str] = None
    error: Optional[str] = None
    # details: Dict[str, Any] = None
    details: Optional[Dict[str, Any]] = None


class UpdateTransactionManager:
    """
    Manages atomic plugin updates with crash recovery.

    Ensures:
    - No partial installs
    - Automatic rollback on failure
    - Recovery after crash
    - Complete audit trail
    """

    def __init__(self, plugins_dir: Path, runtime):
        """
        Initialize transaction manager.

        Args:
            plugins_dir: Directory containing plugins
            runtime: Runtime instance for storage access
        """
        self.plugins_dir = Path(plugins_dir)
        self.runtime = runtime
        self.staging_dir = self.plugins_dir / ".staging"
        self.backup_dir = self.plugins_dir / ".backup"

        # Create directories
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Active transactions (in-memory + persistent)
        self._active_transactions: Dict[str, Transaction] = {}
        self._load_pending_transactions()

    def _load_pending_transactions(self):
        """Load transactions that may need recovery."""
        if self.runtime is None:
            return
        try:
            # Check storage for pending transactions
            pending = self.runtime.storage.get("marketplace.transactions", {})
            if not isinstance(pending, dict):
                pending = {}
            for txn_id, txn_data in pending.items():
                txn = self._deserialize_transaction(txn_data)
                # If crashed during swap, mark for recovery
                if txn.state in [
                    TransactionState.SWAPPING,
                    TransactionState.ACTIVATING,
                ]:
                    logger.warning(
                        f"Found pending transaction {txn_id} in state {txn.state.value}"
                    )
                    self._active_transactions[txn_id] = txn
        except STORAGE_BOUNDARY_ERRORS:
            logger.error(
                "UpdateTransactionManager: load pending transactions storage boundary",
                exc_info=True,
            )
        except Exception as e:
            logger.error(
                "Failed to load pending transactions: %s", e, exc_info=True
            )

    async def prepare_install(
        self, plugin_name: str, version: str, archive_path: Path
    ) -> Transaction:
        """
        Begin install transaction.

        Args:
            plugin_name: Name of plugin
            version: Version string
            archive_path: Downloaded plugin archive

        Returns:
            Transaction object (PREPARING state)
        """
        txn_id = f"{plugin_name}_{version}_{int(datetime.now().timestamp())}"
        staging_path = self.staging_dir / plugin_name

        txn = Transaction(
            plugin_name=plugin_name,
            version=version,
            action="install",
            state=TransactionState.PREPARING,
            start_time=datetime.now(timezone.utc).isoformat() + "Z",
            staging_path=str(staging_path),
        )

        self._active_transactions[txn_id] = txn
        self._save_transaction(txn_id, txn)

        return txn

    async def prepare_update(
        self, plugin_name: str, version: str, archive_path: Path
    ) -> Transaction:
        """
        Begin update transaction.

        Args:
            plugin_name: Name of plugin
            version: New version string
            archive_path: Downloaded plugin archive

        Returns:
            Transaction object with backup info
        """
        current_path = self.plugins_dir / plugin_name
        if not current_path.exists():
            raise TransactionError(f"Plugin '{plugin_name}' not found")

        # Get current version
        old_version = "unknown"
        metadata_path = current_path / "metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path) as f:
                    metadata = json.load(f)
                    old_version = metadata.get("version", "unknown")
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                logger.debug(
                    "prepare_update: read metadata.json failed path=%s",
                    metadata_path,
                    exc_info=True,
                )

        txn_id = f"{plugin_name}_{version}_{int(datetime.now().timestamp())}"
        staging_path = self.staging_dir / plugin_name
        backup_path = self.backup_dir / f"{plugin_name}_{old_version}"

        txn = Transaction(
            plugin_name=plugin_name,
            version=version,
            action="update",
            state=TransactionState.PREPARING,
            start_time=datetime.now(timezone.utc).isoformat() + "Z",
            old_version=old_version,
            staging_path=str(staging_path),
            backup_path=str(backup_path),
        )

        self._active_transactions[txn_id] = txn
        self._save_transaction(txn_id, txn)

        return txn

    async def mark_validated(self, txn_id: str):
        """Mark transaction as validated."""
        if txn_id not in self._active_transactions:
            raise TransactionError(f"Transaction {txn_id} not found")

        txn = self._active_transactions[txn_id]
        txn.state = TransactionState.STAGED
        self._save_transaction(txn_id, txn)
        logger.info(f"Transaction {txn_id} validated")

    async def atomic_swap(self, txn_id: str) -> bool:
        """
        Perform atomic directory swap.

        Handles:
        - Backup current version (if update)
        - Swap staging → current
        - Recovery on failure

        Args:
            txn_id: Transaction ID

        Returns:
            True if swap succeeded

        Raises:
            TransactionError: If swap fails
        """
        if txn_id not in self._active_transactions:
            raise TransactionError(f"Transaction {txn_id} not found")

        txn = self._active_transactions[txn_id]
        plugin_name = txn.plugin_name
        current_path = self.plugins_dir / plugin_name
        if not txn.staging_path:
            raise TransactionError(f"Transaction {txn_id} missing staging path")
        staging_path = Path(txn.staging_path)

        if not staging_path.exists():
            raise TransactionError(f"Staging path does not exist: {staging_path}")

        try:
            # Mark as swapping (for crash recovery)
            txn.state = TransactionState.SWAPPING
            self._save_transaction(txn_id, txn)

            # For update: backup current version
            if txn.action == "update" and current_path.exists():
                if not txn.backup_path:
                    raise TransactionError(f"Transaction {txn_id} missing backup path")
                backup_path = Path(txn.backup_path)
                if backup_path.exists():
                    shutil.rmtree(backup_path)

                # Atomic rename current → backup
                os.replace(str(current_path), str(backup_path))
                logger.info(f"Backed up {plugin_name} to {backup_path}")

            # Atomic rename staging → current
            os.replace(str(staging_path), str(current_path))
            logger.info(f"Swapped {plugin_name} to current")

            txn.state = TransactionState.ACTIVATING
            self._save_transaction(txn_id, txn)
            return True

        except Exception as e:
            logger.error(f"Atomic swap failed: {e}")
            # Attempt recovery
            try:
                await self._recover_from_failed_swap(txn_id)
            except Exception as recovery_error:
                logger.error(f"Recovery failed: {recovery_error}")
                raise RollbackError(f"Failed to recover from swap: {recovery_error}")

            raise TransactionError(f"Swap failed: {e}")

    async def _recover_from_failed_swap(self, txn_id: str):
        """
        Recover from failed swap.

        If we crashed during SWAPPING:
        - Check if backup exists
        - If current exists and backup exists → restore backup
        """
        txn = self._active_transactions.get(txn_id)
        if not txn:
            return

        plugin_name = txn.plugin_name
        current_path = self.plugins_dir / plugin_name
        backup_path = Path(txn.backup_path) if txn.backup_path else None

        # If backup exists and current is broken, restore
        if backup_path and backup_path.exists():
            if current_path.exists():
                broken_path = self.plugins_dir / f"{plugin_name}.broken"
                os.replace(str(current_path), str(broken_path))
                logger.warning(f"Moved broken {plugin_name} to {broken_path}")

            os.replace(str(backup_path), str(current_path))
            logger.info(f"Restored {plugin_name} from backup")

    async def commit(self, txn_id: str):
        """
        Mark transaction as committed (success).

        Cleanup: remove backup after successful activation.
        """
        if txn_id not in self._active_transactions:
            raise TransactionError(f"Transaction {txn_id} not found")

        txn = self._active_transactions[txn_id]
        txn.state = TransactionState.COMMITTED
        txn.end_time = datetime.now(timezone.utc).isoformat() + "Z"

        # Clean up backup
        if txn.backup_path:
            backup_path = Path(txn.backup_path)
            if backup_path.exists():
                shutil.rmtree(backup_path)
                logger.info(f"Cleaned up backup {backup_path}")

        # Clean up staging
        if txn.staging_path:
            staging_path = Path(txn.staging_path)
            if staging_path.exists():
                shutil.rmtree(staging_path)

        self._save_transaction(txn_id, txn)
        self._audit_log(txn, "success")
        logger.info(f"Transaction {txn_id} committed")

    async def rollback(self, txn_id: str, reason: str):
        """
        Rollback transaction.

        Handles:
        - Restores backup if available
        - Cleans up staging
        - Records reason
        """
        if txn_id not in self._active_transactions:
            raise TransactionError(f"Transaction {txn_id} not found")

        txn = self._active_transactions[txn_id]
        txn.error = reason
        txn.state = TransactionState.ROLLED_BACK
        txn.end_time = datetime.now(timezone.utc).isoformat() + "Z"

        try:
            plugin_name = txn.plugin_name
            current_path = self.plugins_dir / plugin_name
            backup_path = Path(txn.backup_path) if txn.backup_path else None

            # If we have backup, restore it
            if backup_path and backup_path.exists():
                if current_path.exists():
                    shutil.rmtree(current_path)
                os.replace(str(backup_path), str(current_path))
                logger.info(f"Rolled back {plugin_name} to {txn.old_version}")

            # Clean up staging
            if txn.staging_path:
                staging_path = Path(txn.staging_path)
                if staging_path.exists():
                    shutil.rmtree(staging_path)

            self._save_transaction(txn_id, txn)
            self._audit_log(txn, "rolled_back", reason)

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            raise RollbackError(f"Failed to rollback transaction: {e}")

    def _save_transaction(self, txn_id: str, txn: Transaction):
        """Save transaction state to persistent storage."""
        if self.runtime is None:
            return
        try:
            txn_data = self._serialize_transaction(txn)
            current = self.runtime.storage.get("marketplace.transactions", {})
            if not isinstance(current, dict):
                current = {}
            current[txn_id] = txn_data
            self.runtime.storage.set("marketplace.transactions", current)
        except Exception as e:
            logger.error(f"Failed to save transaction: {e}")

    def _serialize_transaction(self, txn: Transaction) -> Dict[str, Any]:
        """Convert transaction to dict."""
        return {
            "plugin_name": txn.plugin_name,
            "version": txn.version,
            "action": txn.action,
            "state": txn.state.value,
            "start_time": txn.start_time,
            "end_time": txn.end_time,
            "old_version": txn.old_version,
            "backup_path": txn.backup_path,
            "staging_path": txn.staging_path,
            "error": txn.error,
            "details": txn.details or {},
        }

    def _deserialize_transaction(self, data: Dict[str, Any]) -> Transaction:
        """Convert dict to transaction."""
        return Transaction(
            plugin_name=data["plugin_name"],
            version=data["version"],
            action=data["action"],
            state=TransactionState(data["state"]),
            start_time=data["start_time"],
            end_time=data.get("end_time"),
            old_version=data.get("old_version"),
            backup_path=data.get("backup_path"),
            staging_path=data.get("staging_path"),
            error=data.get("error"),
            details=data.get("details") or {},
        )

    def _audit_log(
        self, txn: Transaction, final_status: str, reason: Optional[str] = None
    ):
        """Write audit log entry."""
        if self.runtime is None:
            return
        try:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "action": txn.action,
                "plugin": txn.plugin_name,
                "version": txn.version,
                "old_version": txn.old_version,
                "status": final_status,
                "reason": reason or txn.error,
            }

            audit_log = self.runtime.storage.get("marketplace.audit", {})
            if not isinstance(audit_log, dict):
                audit_log = {}
            log_id = f"{txn.plugin_name}_{int(datetime.now().timestamp() * 1000)}"
            audit_log[log_id] = entry
            self.runtime.storage.set("marketplace.audit", audit_log)

            logger.info(f"Audit: {entry}")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
