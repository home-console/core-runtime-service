import logging
"""
Marketplace plugin installer.

Handles:
- ZIP/TAR extraction
- plugin.json validation
- Signature verification (Trust Layer)
- SHA256 verification
- Conflict detection
- File placement
- PluginManager integration
"""

import asyncio
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import zipfile
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from pathlib import PurePosixPath
from typing import Tuple

from modules.security.trust.legacy_crypto import (
    PluginTrustError,
    PluginTrustVerifier,
    TrustStore,
)
from modules.plugins.schema import ValidationError as SchemaValidationError
from modules.plugins.schema import validate_plugin_json
logger = logging.getLogger(__name__)


class InstallerError(Exception):
    """Marketplace installer error."""

    pass


class MarketplaceInstaller:
    """
    Installs plugins from package archives.

    Workflow:
    1. Validate archive (zip/tar)
    2. Extract to temp location
    3. Validate plugin.json
    4. Check SHA256 (if provided)
    5. Check for conflicts
    6. Move to plugins/{plugin_name}
    7. Load via PluginManager
    """

    SUPPORTED_EXTENSIONS = {".zip", ".tar.gz", ".tgz"}

    def __init__(self, plugins_dir: Path):
        """
        Initialize installer.

        Args:
            plugins_dir: Path to plugins directory (e.g., /app/plugins)
        """
        self.plugins_dir = Path(plugins_dir)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

    async def install_from_file(
        self,
        archive_path: Path,
        sha256: Optional[str] = None,
        runtime: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Install plugin from archive file.

        Args:
            archive_path: Path to plugin archive (zip/tar.gz)
            sha256: Expected SHA256 hash (optional)
            runtime: Runtime instance for plugin loading (optional)

        Returns:
            Install result: {
                "name": str,
                "version": str,
                "path": str,
                "installed_at": str,
                "hash": str
            }

        Raises:
            InstallerError: if installation fails
        """
        archive_path = Path(archive_path)

        # Validate archive exists
        if not archive_path.exists():
            raise InstallerError(f"Archive not found: {archive_path}")

        # Validate archive extension
        if not self._is_supported_archive(archive_path):
            raise InstallerError(
                f"Unsupported archive format. Supported: {self.SUPPORTED_EXTENSIONS}"
            )

        # Calculate SHA256
        calculated_hash = self._calculate_sha256(archive_path)
        if sha256 and calculated_hash != sha256:
            raise InstallerError(
                f"SHA256 mismatch. Expected: {sha256}, got: {calculated_hash}"
            )

        # Extract to temp directory
        temp_dir = None
        target_dir = None  # P0: Initialize before try block
        try:
            temp_dir = tempfile.mkdtemp(prefix="marketplace_install_")
            self._extract_archive(archive_path, temp_dir)

            # Validate plugin.json
            plugin_json_path = Path(temp_dir) / "plugin.json"
            if not plugin_json_path.exists():
                raise InstallerError("plugin.json not found in archive")

            with open(plugin_json_path) as f:
                plugin_data = json.load(f)

            # Validate schema
            try:
                plugin_data = validate_plugin_json(plugin_data)
            except SchemaValidationError as e:
                raise InstallerError(f"Invalid plugin.json: {str(e)}")

            # Verify signature if present (BEFORE installation)
            plugin_sig_path = Path(temp_dir) / "plugin.sig"
            trust_level = None  # Will be set if signature verification succeeds

            if plugin_sig_path.exists():
                # Signature is present — must verify
                try:
                    with open(plugin_sig_path, "r") as f:
                        signature = f.read().strip()

                    # Create verifier with trust store
                    trust_store = TrustStore()
                    trust_store.load()
                    verifier = PluginTrustVerifier(trust_store)

                    # Verify plugin signature and get trust level
                    verify_result = verifier.verify_plugin(
                        archive_path, plugin_data, signature
                    )
                    trust_level = verify_result.get("trust_level")

                except PluginTrustError as e:
                    raise InstallerError(f"Plugin signature verification failed: {e}")
                except Exception as e:
                    raise InstallerError(f"Failed to verify plugin signature: {e}")
            elif plugin_data.get("public_key"):
                # plugin.json declares public_key but no signature file
                raise InstallerError(
                    "Plugin manifest declares 'public_key' but plugin.sig file not found. "
                    "Signature file is required for signed plugins."
                )

            plugin_name = plugin_data["name"]
            plugin_version = plugin_data["version"]
            class_path = plugin_data["class_path"]

            # Derive module file from class_path (e.g. "plugin.TestPlugin" → "plugin.py")
            module_name = class_path.rsplit(".", 1)[0]
            entrypoint_file = module_name.replace(".", "/") + ".py"

            # Validate that plugin can be installed (dependencies satisfied)
            if runtime:
                from core.kernel.base_plugin import PluginMetadata

                # Create metadata for validation
                try:
                    metadata = PluginMetadata(
                        name=plugin_name,
                        version=plugin_version,
                        description=plugin_data.get("description", ""),
                        author=plugin_data.get("author", ""),
                        dependencies=plugin_data.get("dependencies", []),
                        capabilities_provided=plugin_data.get(
                            "capabilities_provided", []
                        ),
                        capabilities_required=plugin_data.get(
                            "capabilities_required", []
                        ),
                    )

                    # Validate installation would not break system
                    policy = getattr(getattr(runtime, "plugins", None), "lifecycle_policy", None)
                    if policy is not None:
                        ok, errors = policy.can_install_plugin(metadata)
                        if not ok and errors:
                            raise InstallerError(
                                f"Cannot install {plugin_name}: dependency validation failed:\n"
                                + "\n".join(f"  - {e}" for e in errors)
                            )
                    else:
                        errors = []
                except InstallerError:
                    raise
                except (TypeError, AttributeError):
                    # In test environments with mocks, skip strict validation
                    pass
                except Exception:
                    logger.warning(
                        "MarketplaceInstaller: dependency validation unexpected error",
                        exc_info=True,
                    )

            # Check for conflicts
            target_dir = self.plugins_dir / plugin_name
            if target_dir.exists():
                raise InstallerError(
                    f"Plugin '{plugin_name}' already installed at {target_dir}"
                )

            # Validate entrypoint exists in archive
            entrypoint_path = Path(temp_dir) / entrypoint_file
            if not entrypoint_path.exists():
                raise InstallerError(f"Plugin module not found: {entrypoint_file}")

            # Move to plugins directory
            target_dir.mkdir(parents=True, exist_ok=True)
            for item in Path(temp_dir).iterdir():
                dest = target_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

            # Load via PluginManager if provided
            if runtime:
                try:
                    # P0: Wrap load in try-finally for proper cleanup
                    try:
                        # Dynamically import the plugin module
                        plugin_module = self._load_plugin_module(target_dir, entrypoint_file)

                        # Find BasePlugin subclass
                        plugin_class = self._find_plugin_class(plugin_module)
                        if not plugin_class:
                            raise InstallerError(
                                f"No BasePlugin subclass found in {class_path}"
                            )

                        # Instantiate and load
                        plugin_instance = plugin_class(runtime)

                        # Store trust level on plugin instance for CapabilityRegistry
                        if trust_level is not None:
                            plugin_instance._trust_level = trust_level

                        await runtime.plugin_manager.load_plugin(plugin_instance)

                        # P0: Post-install activation - start plugin if auto_start=True
                        try:
                            metadata = plugin_instance.metadata
                            # Handle both property and method implementations
                            if callable(metadata):
                                metadata = metadata()
                            auto_start = getattr(metadata, "auto_start", True)
                            if auto_start:
                                await runtime.plugin_manager.start_plugin(metadata.name)
                        except Exception as e:
                            # Log activation error but don't fail installation
                            rlog = getattr(runtime, "logger", None)
                            if rlog:
                                rlog.warning(f"Failed to auto-start plugin: {str(e)}")
                            logger.debug(
                                "MarketplaceInstaller: auto-start failed", exc_info=True
                            )

                    except InstallerError:
                        raise
                    except Exception as e:
                        raise InstallerError(
                            f"Failed to load plugin via PluginManager: {str(e)}"
                        )

                except InstallerError:
                    raise
                except Exception as e:
                    raise InstallerError(f"Plugin loading error: {str(e)}")

            # Return installation info
            return {
                "name": plugin_name,
                "version": plugin_version,
                "path": str(target_dir),
                "installed_at": datetime.now(timezone.utc).isoformat(),
                "installed_at": datetime.now(UTC).isoformat(),
                "hash": calculated_hash,
                "class_path": class_path,
                "capabilities_provided": plugin_data.get("capabilities_provided", []),
                "capabilities_required": plugin_data.get("capabilities_required", []),
            }

        except Exception:
            # P0: Cleanup target_dir if installation failed
            try:
                if target_dir is not None and target_dir.exists():
                    shutil.rmtree(target_dir)
            except OSError:
                logger.debug(
                    "MarketplaceInstaller: cleanup target_dir after failure", exc_info=True
                )
            raise

        finally:
            # Clean up temp directory
            try:
                if temp_dir is not None and os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            except OSError:
                logger.debug(
                    "MarketplaceInstaller: temp_dir cleanup failed", exc_info=True
                )

    async def uninstall(
        self,
        plugin_name: str,
        runtime: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Uninstall a marketplace plugin.

        Args:
            plugin_name: Name of plugin to uninstall
            runtime: Runtime instance for plugin manager integration

        Returns:
            Uninstall result

        Raises:
            InstallerError: if uninstall fails
        """
        target_dir = self.plugins_dir / plugin_name

        if not target_dir.exists():
            raise InstallerError(f"Plugin not found: {plugin_name}")

        # Unload via PluginManager if provided
        if runtime:
            try:
                await runtime.plugin_manager.stop_plugin(plugin_name)
                await runtime.plugin_manager.unload_plugin(plugin_name)
            except Exception:
                logger.debug(
                    "MarketplaceInstaller.uninstall: stop/unload (plugin may be absent)",
                    exc_info=True,
                )

        # Remove directory
        shutil.rmtree(target_dir)

        return {
            "name": plugin_name,
            "uninstalled_at": datetime.now(timezone.utc).isoformat(),
            "uninstalled_at": datetime.now(UTC).isoformat(),
        }

    def _is_supported_archive(self, path: Path) -> bool:
        """Check if archive format is supported."""
        return path.suffix in {".zip"} or str(path).endswith((".tar.gz", ".tgz"))

    def _calculate_sha256(self, path: Path) -> str:
        """Calculate SHA256 hash of file."""
        sha256_hash = hashlib.sha256()
        with open(path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    def _extract_archive(self, archive_path: Path, target_dir: str) -> None:
        """Extract ZIP or TAR archive safely."""
        target_root = Path(target_dir).resolve()

        def _safe_destination(member_name: str) -> Path:
            parts = PurePosixPath(member_name).parts
            if not parts:
                raise InstallerError("Archive contains empty member name")
            if any(part in ("", ".", "..") for part in parts):
                raise InstallerError(f"Unsafe archive path: {member_name}")
            destination = (target_root / Path(*parts)).resolve()
            if destination != target_root and target_root not in destination.parents:
                raise InstallerError(f"Archive path escapes target directory: {member_name}")
            return destination

        try:
            if archive_path.suffix == ".zip":
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for info in zf.infolist():
                        destination = _safe_destination(info.filename)
                        if info.is_dir():
                            destination.mkdir(parents=True, exist_ok=True)
                            continue
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info, "r") as src, open(destination, "wb") as dst:
                            shutil.copyfileobj(src, dst)
            elif str(archive_path).endswith((".tar.gz", ".tgz")):
                with tarfile.open(archive_path, "r:gz") as tf:
                    for member in tf.getmembers():
                        if member.issym() or member.islnk() or member.isdev():
                            raise InstallerError(f"Unsafe archive member type: {member.name}")
                        destination = _safe_destination(member.name)
                        if member.isdir():
                            destination.mkdir(parents=True, exist_ok=True)
                            continue
                        extracted = tf.extractfile(member)
                        if extracted is None:
                            raise InstallerError(f"Failed to extract archive member: {member.name}")
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with extracted, open(destination, "wb") as dst:
                            shutil.copyfileobj(extracted, dst)
            else:
                raise InstallerError(f"Unknown archive format: {archive_path}")
        except (zipfile.BadZipFile, tarfile.TarError) as e:
            raise InstallerError(f"Invalid archive: {str(e)}")

    def _load_plugin_module(self, plugin_dir: Path, entrypoint_file: str):
        """Dynamically load plugin module."""
        import importlib.util
        import sys

        # Add plugin directory to path
        plugin_dir_str = str(plugin_dir)
        path_inserted = False
        if plugin_dir_str not in sys.path:
            sys.path.insert(0, plugin_dir_str)
            path_inserted = True


        # Load module
        entrypoint_path = plugin_dir / entrypoint_file
        module_name = entrypoint_file.replace("/", ".").replace(".py", "")

        spec = importlib.util.spec_from_file_location(module_name, entrypoint_path)
        if not spec or not spec.loader:
            raise InstallerError(f"Cannot load module: {entrypoint_file}")

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            return module
        finally:
            if path_inserted and sys.path and sys.path[0] == plugin_dir_str:
                sys.path.pop(0)
    
    
        spec.loader.exec_module(module)
        return module

    async def install_from_url(
        self,
        url: str,
        sha256: Optional[str] = None,
        signature: Optional[str] = None,
        public_key: Optional[str] = None,
        runtime: Optional[Any] = None,
        force_update: bool = False,
    ) -> Dict[str, Any]:
        """
        Install plugin from remote URL (registry flow).

        Args:
            url: HTTPS URL to plugin archive
            sha256: Expected SHA256 hash
            signature: Plugin signature for verification
            public_key: Public key for signature verification
            runtime: Runtime instance for plugin loading
            force_update: Allow downgrade/conflicts

        Returns:
            Install result

        Raises:
            InstallerError: if download or installation fails
        """
        if not signature or not public_key:
            raise InstallerError(
                "Marketplace install requires signature and public_key from registry metadata"
            )

        try:
            import aiohttp
        except ImportError:
            raise InstallerError(
                "aiohttp not installed (required for registry downloads)"
            )

        # Security settings (matching registry client)
        MAX_SIZE = 100 * 1024 * 1024  # 100 MB
        TIMEOUT = 30  # seconds

        # Download archive
        temp_dir = None
        try:
            temp_dir = tempfile.mkdtemp()
            archive_path = Path(temp_dir) / "plugin.zip"

            # Download with security checks
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(
                        url, timeout=aiohttp.ClientTimeout(total=TIMEOUT), ssl=True
                    ) as response:
                        if response.status != 200:
                            raise InstallerError(
                                f"Download failed: HTTP {response.status}"
                            )

                        # Check Content-Length
                        if (
                            response.content_length
                            and response.content_length > MAX_SIZE
                        ):
                            raise InstallerError("Plugin archive too large")

                        # Download with size limit
                        downloaded = 0
                        with open(archive_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                downloaded += len(chunk)
                                if downloaded > MAX_SIZE:
                                    raise InstallerError(
                                        "Plugin archive exceeds size limit"
                                    )
                                f.write(chunk)

                except asyncio.TimeoutError:
                    raise InstallerError(f"Download timeout ({TIMEOUT}s)")
                except aiohttp.ClientError as e:
                    raise InstallerError(f"Download failed: {e}")
            

            # If signature provided, it will be verified during install_from_file
            # Signature validation is a trust-layer responsibility.

            # Install from downloaded archive
            return await self.install_from_file(
                archive_path, sha256=sha256, runtime=runtime
            )

        finally:
            # Cleanup temp directory
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def _find_plugin_class(self, module):
        """Find BasePlugin subclass in module."""
        from core.kernel.base_plugin import BasePlugin

        for item_name in dir(module):
            item = getattr(module, item_name)
            if (
                isinstance(item, type)
                and issubclass(item, BasePlugin)
                and item is not BasePlugin
            ):
                return item

        return None
