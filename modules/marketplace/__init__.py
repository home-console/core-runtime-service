"""Marketplace module - dynamic plugin installation and management."""

from modules.marketplace.installer import InstallerError, MarketplaceInstaller
from modules.marketplace.module import MarketplaceModule
from modules.marketplace.registry_client import (
    PluginRelease,
    RegistryClient,
    RegistryError,
    RegistryIndex,
    RegistrySecurityError,
)
from modules.marketplace.semver import (
    Version,
    VersionConstraint,
    VersionConstraintError,
    VersionResolver,
)
from modules.marketplace.services import MarketplaceService, MarketplaceServiceError
from modules.marketplace.transaction import (
    RollbackError,
    Transaction,
    TransactionError,
    TransactionState,
    UpdateTransactionManager,
)
from modules.marketplace.update_validator import (
    PluginUpdateValidator,
    UpdateCheck,
    UpdateValidationError,
)

__all__ = [
    "UpdateTransactionManager",
    "Transaction",
    "TransactionError",
    "RollbackError",
    "TransactionState",
    "RegistryClient",
    "RegistryError",
    "RegistryIndex",
    "RegistrySecurityError",
    "PluginRelease",
    "PluginUpdateValidator",
    "UpdateCheck",
    "UpdateValidationError",
    "Version",
    "VersionConstraint",
    "VersionResolver",
    "VersionConstraintError",
    "MarketplaceModule",
    "MarketplaceInstaller",
    "InstallerError",
    "MarketplaceService",
    "MarketplaceServiceError",
]
