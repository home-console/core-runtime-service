"""
Plugin Trust Verifier — cryptographic verification of plugin authenticity.

Responsibilities:
- Verify plugin signatures using trusted public keys
- Enforce trust rules (system.*, admin.* capabilities)
- Support self-hosted bootstrap mode
- Offline verification support
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional
import logging

from core.trust.signature import (
    verify_signature,
    compute_payload_hash,
    compute_archive_sha256,
    SignatureError
)
from core.trust.trust_store import TrustStore, TrustLevel, TrustError

logger = logging.getLogger(__name__)


class PluginTrustError(Exception):
    """Plugin trust verification failed."""
    pass


class PluginTrustVerifier:
    """
    Verify plugin signatures and enforce trust rules.
    
    Workflow:
    1. Extract plugin.json and plugin.sig from archive
    2. Compute archive SHA256
    3. Create payload: (manifest_json + archive_hash)
    4. Verify signature using public_key from manifest
    5. Check if public_key is trusted
    6. Enforce capability security rules
    """
    
    def __init__(self, trust_store: Optional[TrustStore] = None):
        """
        Initialize verifier with trust store.
        
        Args:
            trust_store: TrustStore instance (creates default if None)
        """
        if trust_store is None:
            trust_store = TrustStore()
        
        self.trust_store = trust_store
        self.trust_store.load()
    
    def verify_plugin(
        self,
        archive_path: Path,
        manifest: Dict[str, Any],
        signature: str
    ) -> Dict[str, Any]:
        """
        Verify plugin signature and trust.
        
        Step 11: Returns trust level for use in capability registration.
        
        Args:
            archive_path: Path to plugin archive
            manifest: Parsed plugin.json
            signature: Base64-encoded signature (plugin.sig content)
            
        Returns:
            Dict with verification results:
            {
                'trusted': True,
                'trust_level': TrustLevel.CORE,
                'public_key': str,
                'key_id': str
            }
            
        Raises:
            PluginTrustError: if verification fails
        """
        # Step 1: Check public key exists in manifest
        public_key = manifest.get('public_key')
        if not public_key:
            raise PluginTrustError("Plugin manifest missing 'public_key' field")
        
        # Step 2: Compute archive hash
        try:
            archive_hash = compute_archive_sha256(archive_path)
        except Exception as e:
            raise PluginTrustError(f"Failed to compute archive hash: {e}")
        
        # Step 3: Create payload for verification
        manifest_json = json.dumps(manifest, sort_keys=True)
        payload = compute_payload_hash(manifest_json, archive_hash)
        
        # Step 4: Verify signature
        try:
            verify_signature(payload, public_key, signature)
        except SignatureError as e:
            raise PluginTrustError(f"Signature verification failed: {e}")
        
        # Step 5: Check if public key is trusted
        trust_level = None
        key_id = None
        
        if self.trust_store.is_empty():
            # Self-hosted mode: auto-trust first key with warning
            logger.warning(
                f"Trust store is empty. Auto-trusting plugin key '{public_key[:16]}...' "
                "in self-hosted mode. This is ONLY safe in controlled environments."
            )
            key_id = manifest.get('name', 'unknown-plugin')
            trust_level = TrustLevel.DEVELOPER
            self.trust_store.add_key(
                key_id=key_id,
                public_key=public_key,
                level=trust_level,
                description=f"Auto-trusted: {manifest.get('name')}"
            )
        elif not self.trust_store.is_key_trusted(public_key):
            raise PluginTrustError(
                f"Plugin signed with untrusted key. Key not found in trust store. "
                f"Key: {public_key[:32]}..."
            )
        else:
            # Key is trusted — get its trust level
            for entry in self.trust_store.list_trusted_keys():
                if entry['public_key'] == public_key:
                    key_id = entry['key_id']
                    trust_level = TrustLevel(entry['level'])
                    break
        
        # Step 6: Enforce capability security rules
        self._verify_capability_claims(manifest, public_key)
        
        # Return verification result with trust level
        return {
            'trusted': True,
            'trust_level': trust_level,
            'public_key': public_key,
            'key_id': key_id
        }
    
    def _verify_capability_claims(
        self,
        manifest: Dict[str, Any],
        public_key: str
    ) -> None:
        """
        Enforce capability security rules.
        
        Rules:
        - system.* capabilities → only for CORE trust level
        - admin.* capabilities → only for PUBLISHER or CORE level
        
        Args:
            manifest: Plugin manifest
            public_key: Public key used for signing
            
        Raises:
            PluginTrustError: if capability claims violate rules
        """
        capabilities = manifest.get('capabilities_provided', [])
        if not isinstance(capabilities, list):
            capabilities = []
        
        # Check key trust level
        key_entry = None
        for entry in self.trust_store.list_trusted_keys():
            if entry['public_key'] == public_key:
                key_entry = entry
                break
        
        if not key_entry:
            # Key is not in trust store (shouldn't happen after verify_plugin)
            raise PluginTrustError("Capability verification: key not found in trust store")
        
        key_level = TrustLevel(key_entry['level'])
        
        # Enforce system.* rule
        system_caps = [cap for cap in capabilities if cap.startswith('system.')]
        if system_caps and key_level != TrustLevel.CORE:
            raise PluginTrustError(
                f"Cannot claim system.* capabilities with {key_level.value} trust level. "
                f"Required: core. Capabilities: {system_caps}"
            )
        
        # Enforce admin.* rule
        admin_caps = [cap for cap in capabilities if cap.startswith('admin.')]
        if admin_caps and key_level == TrustLevel.DEVELOPER:
            raise PluginTrustError(
                f"Cannot claim admin.* capabilities with developer trust level. "
                f"Required: publisher or core. Capabilities: {admin_caps}"
            )
    
    def get_signature_info(self, archive_path: Path, manifest: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get information about plugin signature (for inspection/debugging).
        
        Args:
            archive_path: Path to plugin archive
            manifest: Plugin manifest
            
        Returns:
            Dict with signature information
        """
        public_key = manifest.get('public_key')
        if not public_key:
            return {'signed': False}
        
        try:
            archive_hash = compute_archive_sha256(archive_path)
        except Exception:
            archive_hash = None
        
        is_trusted = self.trust_store.is_key_trusted(public_key)
        key_entry = None
        for entry in self.trust_store.list_trusted_keys():
            if entry['public_key'] == public_key:
                key_entry = entry
                break
        
        return {
            'signed': True,
            'public_key': public_key,
            'key_id': key_entry.get('key_id') if key_entry else None,
            'trusted': is_trusted,
            'trust_level': key_entry.get('level') if key_entry else None,
            'archive_hash': archive_hash
        }
