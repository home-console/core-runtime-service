"""
Registry Client — fetch and resolve plugins from remote registry.

Manages:
- Remote registry index fetching
- Local caching with TTL
- Version resolution
- Channel selection
- SHA256 validation
- SSRF protection
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from core.adapters.storage_errors import STORAGE_BOUNDARY_ERRORS
from modules.marketplace.semver import VersionResolver, VersionConstraintError

logger = logging.getLogger(__name__)


class RegistryError(Exception):
    """Registry operation failed."""
    pass


class RegistrySecurityError(Exception):
    """Registry security check failed (SSRF, unsigned, etc)."""
    pass


@dataclass
class PluginRelease:
    """Single plugin release metadata."""
    name: str
    version: str
    url: str
    sha256: str
    signature: str
    public_key: str
    description: Optional[str] = None
    channel: str = "stable"


@dataclass
class RegistryIndex:
    """Remote registry index structure."""
    registry_version: int
    updated_at: str
    plugins: Dict[str, Any]  # Raw plugin entries


class RegistryClient:
    """
    Client for managing plugin registry.
    
    Responsibilities:
    - Fetch registry index from remote URL
    - Cache locally with TTL
    - Resolve versions using semver
    - Validate registry integrity
    - SSRF protection
    """
    
    # Security settings
    MAX_DOWNLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
    DOWNLOAD_TIMEOUT = 30  # seconds
    CACHE_TTL = 3600  # 1 hour
    
    def __init__(self,
                 registry_url: str,
                 cache_dir: Optional[Path] = None):
        """
        Initialize registry client.
        
        Args:
            registry_url: HTTPS URL to registry (e.g., https://registry.example.com/index.json)
            cache_dir: Local cache directory (~/.homeconsole/marketplace/cache)
            
        Raises:
            RegistrySecurityError: if URL is not HTTPS or points to internal IP
        """
        self._validate_registry_url(registry_url)
        self._registry_url = registry_url
        
        # Setup cache directory
        if cache_dir is None:
            base = os.environ.get("HOMECONSOLE_HOME")
            if base:
                cache_dir = Path(base) / "marketplace" / "cache"
            else:
                cache_dir = Path.cwd() / "data" / "homeconsole" / "marketplace" / "cache"
        base_cache_dir = Path(cache_dir)
        url_fingerprint = hashlib.sha256(registry_url.encode("utf-8")).hexdigest()[:32]
        self._cache_dir = base_cache_dir / f"registry-{url_fingerprint}"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        
        self._cache_path = self._cache_dir / "registry-index.json"
        self._cache_time_path = self._cache_dir / "registry-index.timestamp"
        
        self._index: Optional[RegistryIndex] = None
        self._index_fetched_at: Optional[float] = None
        
        # Registry version downgrade protection
        self._cached_registry_version = self._load_cached_registry_version()
        self._registry_version_path = self._cache_dir / "registry-version.txt"
    
    @staticmethod
    def _validate_registry_url(url: str):
        """
        Validate registry URL for security.
        
        Checks:
        - Must be HTTPS
        - Must not point to internal IPs (SSRF protection)
        
        Args:
            url: Registry URL
            
        Raises:
            RegistrySecurityError: if URL fails validation
        """
        # In development, allow HTTP and localhost to support local marketplace-api.
        # IMPORTANT: do not enable this in production.
        if os.getenv("MARKETPLACE_ALLOW_LOCALHOST", "false").lower() == "true":
            if not (url.startswith("https://") or url.startswith("http://")):
                raise RegistrySecurityError("Registry URL must be HTTP(S)")
            return

        # Must be HTTPS
        if not url.startswith("https://"):
            raise RegistrySecurityError("Registry URL must be HTTPS only")
        
        # Parse hostname
        try:
            # Extract hostname from URL
            import urllib.parse
            parsed = urllib.parse.urlparse(url)
            hostname = parsed.hostname
        except (TypeError, ValueError) as e:
            raise RegistrySecurityError(f"Invalid URL: {e}")
        
        if not hostname:
            raise RegistrySecurityError("Invalid registry URL: no hostname")
        
        # Reject internal IPs (SSRF protection)
        internal_patterns = [
            r"^localhost$",
            r"^127\.",                      # 127.0.0.0/8
            r"^10\.",                       # 10.0.0.0/8
            r"^172\.(1[6-9]|2[0-9]|3[01])",  # 172.16.0.0/12
            r"^192\.168\.",                 # 192.168.0.0/16
            r"^169\.254\.",                 # 169.254.0.0/16 (link-local)
            r"^::1$",                       # IPv6 loopback
            r"^fe80:",                      # IPv6 link-local
        ]
        
        for pattern in internal_patterns:
            if re.match(pattern, hostname, re.IGNORECASE):
                raise RegistrySecurityError(
                    f"SSRF protection: registry URL points to internal IP '{hostname}'"
                )
    
    async def fetch_index(self, force_refresh: bool = False) -> RegistryIndex:
        """
        Fetch registry index from remote or cache.
        
        Caching logic:
        - Return cached index if fresh (TTL not expired)
        - Fetch from remote if cache expired or force_refresh=True
        - Validate registry_version and schema
        
        Args:
            force_refresh: Bypass cache and fetch from remote
            
        Returns:
            RegistryIndex object
            
        Raises:
            RegistryError: if fetch or validation fails
        """
        # Check cache
        if not force_refresh and self._is_cache_fresh():
            logger.info(f"Using cached registry index from {self._cache_path}")
            return self._load_cached_index()
        
        # Fetch from remote
        logger.info(f"Fetching registry index from {self._registry_url}")
        try:
            index_data = await self._fetch_remote_index()
        except RegistryError as e:
            if self._cache_path.exists():
                logger.warning(
                    "Failed to fetch registry, using stale cache: %s", e, exc_info=True
                )
                return self._load_cached_index()
            raise
        except (OSError, asyncio.TimeoutError) as e:
            if self._cache_path.exists():
                logger.warning(
                    "Failed to fetch registry (IO/timeout), using stale cache: %s",
                    e,
                    exc_info=True,
                )
                return self._load_cached_index()
            raise RegistryError(f"Failed to fetch registry: {e}") from e
        except Exception as e:
            if self._cache_path.exists():
                logger.warning(
                    "Failed to fetch registry, using stale cache: %s", e, exc_info=True
                )
                return self._load_cached_index()
            raise RegistryError(f"Failed to fetch registry: {e}") from e
        
        # Validate and parse
        index = self._parse_and_validate_index(index_data)
        
        # Cache locally
        self._save_cache(index_data)
        
        self._index = index
        self._index_fetched_at = time.time()
        
        return index
    
    async def _fetch_remote_index(self) -> Dict[str, Any]:
        """
        Fetch registry index from remote URL.
        
        Security checks:
        - Check Content-Length before download
        - Enforce timeout
        - Validate JSON structure
        
        Raises:
            RegistryError: if fetch fails
        """
        try:
            import aiohttp
        except ImportError:
            raise RegistryError("aiohttp not installed (required for remote registry)")
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    self._registry_url,
                    timeout=aiohttp.ClientTimeout(total=self.DOWNLOAD_TIMEOUT),
                    ssl=True  # Enforce SSL/TLS
                ) as response:
                    # Check status
                    if response.status != 200:
                        raise RegistryError(f"Registry returned HTTP {response.status}")
                    
                    # Check Content-Length
                    content_length = response.content_length
                    if content_length and content_length > self.MAX_DOWNLOAD_SIZE:
                        raise RegistryError(
                            f"Registry index too large: {content_length} bytes "
                            f"(max {self.MAX_DOWNLOAD_SIZE})"
                        )
                    
                    # Read body
                    body = await response.read()
                    
                    # Check actual size
                    if len(body) > self.MAX_DOWNLOAD_SIZE:
                        raise RegistryError("Registry index exceeds size limit")
                    
                    # Parse JSON
                    try:
                        return json.loads(body.decode('utf-8'))
                    except json.JSONDecodeError as e:
                        raise RegistryError(f"Invalid JSON in registry: {e}")
            
            except asyncio.TimeoutError:
                raise RegistryError(f"Registry request timeout ({self.DOWNLOAD_TIMEOUT}s)")
            except aiohttp.ClientError as e:
                raise RegistryError(f"Network error fetching registry: {e}")
    
    def _parse_and_validate_index(self, data: Dict[str, Any]) -> RegistryIndex:
        """
        Parse and validate registry index.

        Checks:
        - registry_version exists and is supported
        - plugins is dict
        - Each plugin has required metadata

        Raises:
            RegistryError: if validation fails
        """
        # Check registry_version
        if "registry_version" not in data:
            raise RegistryError("Missing registry_version")

        registry_version = data.get("registry_version")
        if registry_version != 1:
            raise RegistryError(f"Unsupported registry version: {registry_version}")

        # Prevent registry downgrade attacks
        if self._cached_registry_version is not None:
            if registry_version < self._cached_registry_version:
                raise RegistrySecurityError(
                    f"Registry downgrade detected: cached={self._cached_registry_version}, "
                    f"new={registry_version}"
                )

        # Check plugins structure
        if "plugins" not in data:
            raise RegistryError("Missing 'plugins' section")

        plugins = data.get("plugins", {})
        if not isinstance(plugins, dict):
            raise RegistryError("'plugins' must be a dict")

        # Validate each plugin entry
        for plugin_name, plugin_data in plugins.items():
            self._validate_plugin_entry(plugin_name, plugin_data)

        return RegistryIndex(
            registry_version=registry_version,
            updated_at=data.get("updated_at", ""),
            plugins=plugins
        )

    def _validate_plugin_entry(self, plugin_name: str, plugin_data: Dict[str, Any]):
        """
        Validate single plugin entry.

        Each plugin release requires:
        - url (must be HTTPS)
        - sha256
        - signature
        - public_key

        Raises:
            RegistryError: if validation fails
        """
        if not isinstance(plugin_data, dict):
            raise RegistryError(f"Plugin '{plugin_name}' must be dict")

        # Check channels
        channels = plugin_data.get("channels", {})
        if not isinstance(channels, dict):
            raise RegistryError(f"Plugin '{plugin_name}' channels must be dict")

        # Validate each channel
        for channel_name, channel_data in channels.items():
            self._validate_release(plugin_name, channel_name, channel_data)

        # Check versions
        versions = plugin_data.get("versions", {})
        if not isinstance(versions, dict):
            raise RegistryError(f"Plugin '{plugin_name}' versions must be dict")

        for version_str, version_data in versions.items():
            self._validate_release(plugin_name, version_str, version_data)
    
    def _validate_release(self, plugin_name: str,
                         release_id: str, release_data: Dict[str, Any]):
        """
        Validate plugin release metadata.
        
        Raises:
            RegistryError: if validation fails
        """
        # Required fields
        required = ["url", "sha256", "signature", "public_key"]
        for field in required:
            if field not in release_data:
                raise RegistryError(
                    f"Plugin '{plugin_name}' release '{release_id}' "
                    f"missing required field '{field}'"
                )
        
        # Validate URL (must be HTTPS)
        url = release_data.get("url", "")
        if not url.startswith("https://"):
            raise RegistryError(
                f"Plugin '{plugin_name}' release '{release_id}' "
                f"URL must be HTTPS"
            )
        
        # Validate SHA256 format
        sha256 = release_data.get("sha256", "")
        if not re.match(r"^[a-f0-9]{64}$", sha256.lower()):
            raise RegistrySecurityError(
                f"Plugin '{plugin_name}' release '{release_id}' "
                f"invalid SHA256 format"
            )
        
        # Validate signature is base64-like
        signature = release_data.get("signature", "")
        if not signature or len(signature) < 10:
            raise RegistrySecurityError(
                f"Plugin '{plugin_name}' release '{release_id}' "
                f"invalid or missing signature"
            )
        
        # Validate public_key is base64-like
        public_key = release_data.get("public_key", "")
        if not public_key or len(public_key) < 20:
            raise RegistrySecurityError(
                f"Plugin '{plugin_name}' release '{release_id}' "
                f"invalid or missing public_key"
            )
    
    def _is_cache_fresh(self) -> bool:
        """Check if cache is still valid (within TTL)."""
        if not self._cache_time_path.exists():
            return False
        
        try:
            with open(self._cache_time_path, 'r') as f:
                cache_time = float(f.read().strip())
        except (OSError, ValueError):
            return False
        
        age = time.time() - cache_time
        return age < self.CACHE_TTL
    
    def _load_cached_index(self) -> RegistryIndex:
        """Load registry index from cache."""
        try:
            with open(self._cache_path, 'r') as f:
                data = json.load(f)
            return self._parse_and_validate_index(data)
        except Exception as e:
            raise RegistryError(f"Failed to load cache: {e}")
    
    def _load_cached_registry_version(self) -> Optional[int]:
        """Load cached registry version for downgrade detection."""
        registry_version_path = self._cache_dir / "registry-version.txt"
        if registry_version_path.exists():
            try:
                with open(registry_version_path, 'r') as f:
                    return int(f.read().strip())
            except (OSError, ValueError):
                logger.debug(
                    "_load_cached_registry_version: read failed", exc_info=True
                )
        return None
    
    def _save_cache(self, data: Dict[str, Any]):
        """Save registry index to cache."""
        try:
            with open(self._cache_path, 'w') as f:
                json.dump(data, f)
            with open(self._cache_time_path, 'w') as f:
                f.write(str(time.time()))
            
            # Save registry version for downgrade detection
            registry_version = data.get("registry_version")
            if registry_version:
                with open(self._registry_version_path, 'w') as f:
                    f.write(str(registry_version))
                self._cached_registry_version = registry_version
        except STORAGE_BOUNDARY_ERRORS:
            logger.warning(
                "RegistryClient._save_cache: cache write boundary", exc_info=True
            )
        except Exception as e:
            logger.warning("Failed to save cache: %s", e, exc_info=True)
    
    async def resolve(self,
                     plugin_name: str,
                     version_constraint: Optional[str] = None,
                     channel: str = "stable",
                     include_prerelease: bool = False) -> PluginRelease:
        """
        Resolve plugin version and return release metadata.
        
        Resolution logic:
        1. Fetch registry index (cached if fresh)
        2. Get plugin entry
        3. Resolve version using constraint
        4. Return release metadata with download URL + hash + signature
        
        Args:
            plugin_name: Plugin to resolve
            version_constraint: Semver constraint (e.g., "^1.2.0")
                              If None, uses latest version in channel
            channel: Release channel ("stable", "beta", etc)
            include_prerelease: Include pre-release versions
            
        Returns:
            PluginRelease with download URL and metadata
            
        Raises:
            RegistryError: if plugin not found or resolution fails
        """
        # Fetch index
        index = await self.fetch_index()
        
        # Get plugin
        if plugin_name not in index.plugins:
            raise RegistryError(f"Plugin '{plugin_name}' not found in registry")
        
        plugin_data = index.plugins[plugin_name]
        
        # Get channel or versions
        if version_constraint is None:
            # Use latest from channel
            channels = plugin_data.get("channels", {})
            if channel not in channels:
                raise RegistryError(
                    f"Plugin '{plugin_name}' has no '{channel}' release"
                )
            
            release_data = channels[channel]
            version = release_data.get("version")
            if not version:
                raise RegistryError(f"Channel '{channel}' missing version")
        else:
            # Resolve version from constraint
            versions = plugin_data.get("versions", {})
            if not versions:
                # No versions dict — fall back to channel-based resolution
                channels = plugin_data.get("channels", {})
                if channel not in channels:
                    raise RegistryError(
                        f"Plugin '{plugin_name}' has no versions and no '{channel}' release"
                    )
                release_data = channels[channel]
                version = release_data.get("version")
                if not version:
                    raise RegistryError(f"Channel '{channel}' missing version")
            else:
                resolver = VersionResolver(
                    list(versions.keys()),
                    include_prerelease=include_prerelease
                )

                try:
                    resolved_version = resolver.resolve(version_constraint)
                except VersionConstraintError as e:
                    raise RegistryError(f"Failed to resolve version: {e}")

                if resolved_version is None:
                    raise RegistryError(
                        f"No version matching '{version_constraint}' "
                        f"for plugin '{plugin_name}'"
                    )

                version = str(resolved_version)
                release_data = versions[version]
        
        # Build release metadata
        return PluginRelease(
            name=plugin_name,
            version=version,
            url=release_data.get("url", ""),
            sha256=release_data.get("sha256", ""),
            signature=release_data.get("signature", ""),
            public_key=release_data.get("public_key", ""),
            description=release_data.get("description"),
            channel=channel
        )
