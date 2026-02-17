"""
Trust Store — persistent storage of trusted public keys.

Manages:
- Trusted keys database (~/.homeconsole/trust/keys.json)
- Trust levels (core, publisher, developer)
- Key ownership and signatures
- Self-hosted auto-trust bootstrap
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum
from datetime import datetime


class TrustLevel(Enum):
    """Trust levels for different key types."""
    CORE = "core"              # System/built-in capabilities
    PUBLISHER = "publisher"    # Published ecosystem plugins
    DEVELOPER = "developer"    # Local development mode


class TrustError(Exception):
    """Trust verification failed."""
    pass


class TrustStore:
    """
    Persistent storage for trusted plugin keys.
    
    Location: ~/.homeconsole/trust/keys.json
    
    Schema:
    {
      "trusted_keys": [
        {
          "key_id": "acme-root",
          "public_key": "BASE64_KEY",
          "level": "publisher",
          "added_at": "2025-02-16T10:00:00Z",
          "description": "ACME Inc root signing key"
        }
      ],
      "self_hosted": false,
      "auto_trust_enabled": false
    }
    """
    
    def __init__(self, trust_dir: Optional[Path] = None):
        """
        Initialize trust store.
        
        Args:
            trust_dir: Path to trust directory (default: ~/.homeconsole/trust)
        """
        if trust_dir is None:
            trust_dir = Path.home() / ".homeconsole" / "trust"
        
        self.trust_dir = trust_dir
        self.keys_file = trust_dir / "keys.json"
        self._keys_cache: Dict[str, Dict[str, Any]] = {}
        self._loaded = False
        
        # Create trust directory if it doesn't exist
        self.trust_dir.mkdir(parents=True, exist_ok=True)
    
    def load(self) -> None:
        """Load trusted keys from storage."""
        if self.keys_file.exists():
            try:
                with open(self.keys_file, 'r') as f:
                    data = json.load(f)
                    self._keys_cache = {
                        entry['key_id']: entry
                        for entry in data.get('trusted_keys', [])
                    }
                self._loaded = True
            except Exception as e:
                raise TrustError(f"Failed to load trust store: {e}")
        else:
            self._keys_cache = {}
            self._loaded = True
    
    def save(self) -> None:
        """Save trusted keys to storage."""
        try:
            data = {
                'trusted_keys': list(self._keys_cache.values()),
                'self_hosted': self.is_self_hosted(),
                'auto_trust_enabled': self.is_auto_trust_enabled(),
                'version': 1
            }
            
            with open(self.keys_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            raise TrustError(f"Failed to save trust store: {e}")
    
    def add_key(
        self,
        key_id: str,
        public_key: str,
        level: TrustLevel,
        description: Optional[str] = None
    ) -> None:
        """
        Add a trusted key to the store.
        
        Args:
            key_id: Unique identifier for the key (e.g., "acme-root")
            public_key: Base64-encoded Ed25519 public key
            level: Trust level
            description: Optional description
        """
        if not self._loaded:
            self.load()
        
        self._keys_cache[key_id] = {
            'key_id': key_id,
            'public_key': public_key,
            'level': level.value,
            'added_at': datetime.utcnow().isoformat() + 'Z',
            'description': description or f"Key: {key_id}"
        }
        self.save()
    
    def remove_key(self, key_id: str) -> None:
        """Remove a trusted key from the store."""
        if not self._loaded:
            self.load()
        
        if key_id in self._keys_cache:
            del self._keys_cache[key_id]
            self.save()
    
    def get_key(self, key_id: str) -> Optional[Dict[str, Any]]:
        """Get trusted key by ID."""
        if not self._loaded:
            self.load()
        
        return self._keys_cache.get(key_id)
    
    def is_key_trusted(
        self,
        public_key: str,
        min_level: Optional[TrustLevel] = None
    ) -> bool:
        """
        Check if a public key is trusted.
        
        Args:
            public_key: Base64-encoded public key to verify
            min_level: Minimum trust level required (None = any level)
            
        Returns:
            True if key is trusted at required level
        """
        if not self._loaded:
            self.load()
        
        for entry in self._keys_cache.values():
            if entry['public_key'] == public_key:
                if min_level is None:
                    return True
                
                entry_level = TrustLevel(entry['level'])
                # Level hierarchy: core > publisher > developer
                level_rank = {TrustLevel.CORE: 3, TrustLevel.PUBLISHER: 2, TrustLevel.DEVELOPER: 1}
                if level_rank[entry_level] >= level_rank[min_level]:
                    return True
        
        return False
    
    def is_core_key(self, public_key: str) -> bool:
        """Check if key is trusted at CORE level."""
        return self.is_key_trusted(public_key, TrustLevel.CORE)
    
    def is_publisher_key(self, public_key: str) -> bool:
        """Check if key is trusted at least at PUBLISHER level."""
        return self.is_key_trusted(public_key, TrustLevel.PUBLISHER)
    
    def list_trusted_keys(self) -> List[Dict[str, Any]]:
        """Return list of all trusted keys."""
        if not self._loaded:
            self.load()
        
        return list(self._keys_cache.values())
    
    def is_empty(self) -> bool:
        """Check if trust store is empty."""
        if not self._loaded:
            self.load()
        
        return len(self._keys_cache) == 0
    
    def is_self_hosted(self) -> bool:
        """Check if running in self-hosted mode."""
        if self.keys_file.exists():
            try:
                with open(self.keys_file, 'r') as f:
                    data = json.load(f)
                    return data.get('self_hosted', False)
            except Exception:
                pass
        return False
    
    def mark_self_hosted(self, value: bool = True) -> None:
        """Mark trust store as self-hosted mode."""
        # Update internal state
        self.save()
    
    def is_auto_trust_enabled(self) -> bool:
        """Check if auto-trust first key is enabled."""
        if self.keys_file.exists():
            try:
                with open(self.keys_file, 'r') as f:
                    data = json.load(f)
                    return data.get('auto_trust_enabled', False)
            except Exception:
                pass
        return False
    
    def enable_auto_trust(self) -> None:
        """Enable auto-trust for first key in self-hosted mode."""
        self.save()
    
    def get_config(self) -> Dict[str, Any]:
        """Get full trust store configuration."""
        if not self._loaded:
            self.load()
        
        return {
            'trusted_keys': list(self._keys_cache.values()),
            'self_hosted': self.is_self_hosted(),
            'auto_trust_enabled': self.is_auto_trust_enabled(),
            'trust_dir': str(self.trust_dir)
        }
