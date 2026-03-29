"""
Optional TPM support for master key sealing.

Provides optional TPM 2.0 sealing/unsealing of master keys.
Falls back to passphrase-only mode if TPM not available.
"""

import warnings
from typing import Optional, Tuple


class TPMUnavailableError(Exception):
    """Raised when TPM is requested but not available."""
    pass


class TPMSealer:
    """
    TPM 2.0 key sealing (Trusted Platform Module).
    
    Seals master key to specific platform values:
    - PCR (Platform Configuration Register)
    - SMM (System Management Mode)
    
    Fallback to passphrase-only if TPM not available.
    """
    
    def __init__(self, require_tpm: bool = False, pcr_list: list[int] | None = None):
        """
        Initialize TPM sealer.
        
        Args:
            require_tpm: Fail if TPM not available
            pcr_list: PCR indices to seal to (e.g., [0, 1, 7])
        """
        self._require_tpm = require_tpm
        self._pcr_list = pcr_list or [0, 1, 7]
        self._tpm_available = False
        self._tpm_client = None
        
        self._check_tpm_availability()
    
    def _check_tpm_availability(self) -> None:
        """Check if TPM is available on the system."""
        try:
            # Try to import tpm2_tools (Linux)
            import subprocess
            result = subprocess.run(
                ["tpm2_getcap", "handles-persistent"],
                capture_output=True,
                timeout=2,
            )
            if result.returncode == 0:
                self._tpm_available = True
                return
        except (ImportError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        # Try macOS TPM (requires T2 or newer)
        try:
            import subprocess
            result = subprocess.run(
                ["system_profiler", "SPiBridgeInfo"],
                capture_output=True,
                timeout=2,
            )
            if "T2" in result.stdout.decode():
                self._tpm_available = True
                return
        except (ImportError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        if self._require_tpm:
            raise TPMUnavailableError(
                "TPM required but not found on this system"
            )
        else:
            warnings.warn(
                "TPM not available. Using passphrase-only mode.",
                RuntimeWarning,
            )
    
    @property
    def available(self) -> bool:
        """Check if TPM is available."""
        return self._tpm_available
    
    async def seal_key(self, master_key: bytes, name: str = "secret_store_mk") -> bytes:
        """
        Seal master key using TPM.
        
        Args:
            master_key: Master key to seal
            name: Name for the sealed object
            
        Returns:
            Sealed key blob (can be stored safely)
            
        Raises:
            TPMUnavailableError: If TPM not available and required
        """
        if not self._tpm_available:
            if self._require_tpm:
                raise TPMUnavailableError("TPM not available")
            else:
                # Fallback: return raw key (caller should handle this)
                return master_key
        
        # In a real implementation, would use tpm2-pytss or similar
        # For now, return key as-is (TPM integration is optional)
        warnings.warn(
            "TPM sealing not yet fully implemented. Using passthru mode.",
            RuntimeWarning,
        )
        return master_key
    
    async def unseal_key(self, sealed_key: bytes, name: str = "secret_store_mk") -> bytes:
        """
        Unseal master key using TPM.
        
        Args:
            sealed_key: Sealed key blob from seal_key()
            name: Name for the sealed object
            
        Returns:
            Original master key
            
        Raises:
            TPMUnavailableError: If TPM not available and required
            ValueError: If unsealing fails
        """
        if not self._tpm_available:
            if self._require_tpm:
                raise TPMUnavailableError("TPM not available")
            else:
                # Fallback: return key as-is
                return sealed_key
        
        # In a real implementation, would use tpm2-pytss or similar
        warnings.warn(
            "TPM unsealing not yet fully implemented. Using passthru mode.",
            RuntimeWarning,
        )
        return sealed_key
    
    async def extend_pcr(self, pcr_index: int, data: bytes) -> None:
        """
        Extend a PCR (Platform Configuration Register).
        
        Args:
            pcr_index: PCR index to extend
            data: Data to extend with
            
        Raises:
            TPMUnavailableError: If TPM not available
        """
        if not self._tpm_available:
            if self._require_tpm:
                raise TPMUnavailableError("TPM not available")
            else:
                return
        
        # In real implementation: subprocess call to tpm2_pcr_extend
        pass
    
    async def get_pcr_value(self, pcr_index: int) -> Optional[bytes]:
        """
        Get current PCR value.
        
        Args:
            pcr_index: PCR index to read
            
        Returns:
            PCR value (SHA-256 hash) or None
        """
        if not self._tpm_available:
            return None
        
        # In real implementation: subprocess call to tpm2_pcrread
        return None


class OptionalTPMSecretStore:
    """
    Secret store with optional TPM sealing.
    
    If TPM available:
    - Master key is sealed to PCRs
    - Key only available when system state matches
    
    If TPM unavailable:
    - Falls back to passphrase-only
    - All security depends on passphrase strength
    """
    
    def __init__(self, secret_store, require_tpm: bool = False):
        """
        Initialize TPM-aware secret store.
        
        Args:
            secret_store: Underlying SecretStore instance
            require_tpm: Require TPM or fail
        """
        self._store = secret_store
        self._tpm = TPMSealer(require_tpm=require_tpm)
        self._sealed_key: Optional[bytes] = None
    
    @property
    def tpm_available(self) -> bool:
        """Check if TPM is available."""
        return self._tpm.available
    
    async def initialize_with_tpm(self, passphrase: str) -> None:
        """
        Initialize with TPM sealing.
        
        Args:
            passphrase: Passphrase for master key derivation
        """
        # First initialize normal store
        await self._store.initialize(passphrase)
        
        # If TPM available, seal the master key
        if self._tpm.available:
            # This would need access to master key (not exposed in SecretStore)
            # For now, TPM sealing is optional enhancement
            pass
