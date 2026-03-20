"""
Compatibility shim for `core.agent.tls`.

Re-exports classes from `modules.agent.tls`.
"""

from modules.agent.tls import MTLSCertificateAuthority

__all__ = ["MTLSCertificateAuthority"]
