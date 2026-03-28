"""Plugin trust verifier - cryptographic verification of plugin authenticity."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from core.trust.signature import (
    SignatureError,
    compute_archive_sha256,
    compute_payload_hash,
    verify_signature,
)
from core.trust.trust_store import TrustLevel, TrustStore

logger = logging.getLogger(__name__)


class PluginTrustError(Exception):
    """Plugin trust verification failed."""


class PluginTrustVerifier:
    """Verify plugin signatures and enforce trust rules."""

    def __init__(self, trust_store: Optional[TrustStore] = None):
        if trust_store is None:
            trust_store = TrustStore()

        self.trust_store = trust_store
        self.trust_store.load()

    def verify_plugin(
        self,
        archive_path: Path,
        manifest: Dict[str, Any],
        signature: str,
    ) -> Dict[str, Any]:
        """Verify plugin signature and trust."""
        public_key = manifest.get("public_key")
        if not public_key:
            raise PluginTrustError("Plugin manifest missing 'public_key' field")

        try:
            archive_hash = compute_archive_sha256(archive_path)
        except Exception as e:
            raise PluginTrustError(f"Failed to compute archive hash: {e}")

        manifest_json = json.dumps(manifest, sort_keys=True)
        payload = compute_payload_hash(manifest_json, archive_hash)

        try:
            verify_signature(payload, public_key, signature)
        except SignatureError as e:
            raise PluginTrustError(f"Signature verification failed: {e}")

        trust_level = None
        key_id = None

        if self.trust_store.is_empty():
            logger.warning(
                "Trust store is empty. Auto-trusting plugin key '%s...' in self-hosted mode.",
                public_key[:16],
            )
            key_id = manifest.get("name", "unknown-plugin")
            trust_level = TrustLevel.DEVELOPER
            self.trust_store.add_key(
                key_id=key_id,
                public_key=public_key,
                level=trust_level,
                description=f"Auto-trusted: {manifest.get('name')}",
            )
        elif not self.trust_store.is_key_trusted(public_key):
            raise PluginTrustError(
                "Plugin signed with untrusted key. Key not found in trust store. "
                f"Key: {public_key[:32]}..."
            )
        else:
            for entry in self.trust_store.list_trusted_keys():
                if entry["public_key"] == public_key:
                    key_id = entry["key_id"]
                    trust_level = TrustLevel(entry["level"])
                    break

        self._verify_capability_claims(manifest, public_key)

        return {
            "trusted": True,
            "trust_level": trust_level,
            "public_key": public_key,
            "key_id": key_id,
        }

    def _verify_capability_claims(self, manifest: Dict[str, Any], public_key: str) -> None:
        capabilities = manifest.get("capabilities_provided", [])
        if not isinstance(capabilities, list):
            capabilities = []

        key_entry = None
        for entry in self.trust_store.list_trusted_keys():
            if entry["public_key"] == public_key:
                key_entry = entry
                break

        if not key_entry:
            raise PluginTrustError("Capability verification: key not found in trust store")

        key_level = TrustLevel(key_entry["level"])

        system_caps = [cap for cap in capabilities if cap.startswith("system.")]
        if system_caps and key_level != TrustLevel.CORE:
            raise PluginTrustError(
                f"Cannot claim system.* capabilities with {key_level.value} trust level. "
                f"Required: core. Capabilities: {system_caps}"
            )

        admin_caps = [cap for cap in capabilities if cap.startswith("admin.")]
        if admin_caps and key_level == TrustLevel.DEVELOPER:
            raise PluginTrustError(
                "Cannot claim admin.* capabilities with developer trust level. "
                f"Required: publisher or core. Capabilities: {admin_caps}"
            )

    def get_signature_info(self, archive_path: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
        public_key = manifest.get("public_key")
        if not public_key:
            return {"signed": False}

        try:
            archive_hash = compute_archive_sha256(archive_path)
        except Exception:
            archive_hash = None

        is_trusted = self.trust_store.is_key_trusted(public_key)
        key_entry = None
        for entry in self.trust_store.list_trusted_keys():
            if entry["public_key"] == public_key:
                key_entry = entry
                break

        return {
            "signed": True,
            "public_key": public_key,
            "key_id": key_entry.get("key_id") if key_entry else None,
            "trusted": is_trusted,
            "trust_level": key_entry.get("level") if key_entry else None,
            "archive_hash": archive_hash,
        }

__all__ = ["PluginTrustVerifier", "PluginTrustError"]
