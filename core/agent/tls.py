"""
Step 15: mTLS Support — CA and certificate generation.

Provides:
- CA certificate generation
- Agent certificate signing
- mTLS validation
"""

from datetime import datetime, timezone, timedelta
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtensionOID
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend
import hashlib


class MTLSCertificateAuthority:
    """
    Certificate Authority for mTLS.
    
    Generates CA cert and issues agent certificates.
    """
    
    def __init__(self, ca_private_key_pem: bytes, ca_cert_pem: bytes):
        """
        Initialize CA with existing keys.
        
        Args:
            ca_private_key_pem: CA private key in PEM format
            ca_cert_pem: CA certificate in PEM format
        """
        self._ca_private_key = serialization.load_pem_private_key(
            ca_private_key_pem,
            password=None,
            backend=default_backend(),
        )
        self._ca_cert = x509.load_pem_x509_certificate(
            ca_cert_pem,
            backend=default_backend(),
        )
    
    @staticmethod
    def generate_ca_certificate(
        common_name: str = "HomeConsole CA",
        valid_days: int = 3650,  # 10 years
    ) -> tuple[bytes, bytes]:
        """
        Generate a new CA certificate.
        
        Args:
            common_name: CA common name
            valid_days: Certificate validity (days)
            
        Returns:
            (ca_private_key_pem, ca_cert_pem) tuple
        """
        # Generate RSA key pair for CA
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        
        # Create self-signed CA certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "HomeConsole"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        ])
        
        now = datetime.now(timezone.utc)
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            now
        ).not_valid_after(
            now + timedelta(days=valid_days)
        ).add_extension(
            x509.BasicConstraints(ca=True, path_length=0),
            critical=True,
        ).add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                key_encipherment=False,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        ).sign(
            private_key,
            hashes.SHA256(),
            backend=default_backend(),
        )
        
        # Serialize to PEM
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        
        return private_pem, cert_pem
    
    def issue_agent_certificate(
        self,
        agent_id: str,
        agent_name: str,
        agent_public_key_pem: bytes,
        valid_days: int = 365,  # 1 year
    ) -> bytes:
        """
        Issue a client certificate for an agent.
        
        Args:
            agent_id: Agent ID
            agent_name: Agent name (CN)
            agent_public_key_pem: Agent public key (Ed25519 converted to RSA or same)
            valid_days: Certificate validity (days)
            
        Returns:
            Agent certificate in PEM format
        """
        # For now, we'll use RSA for certificate signing
        # In production, you'd convert Ed25519 public key appropriately
        
        # Generate RSA key for the agent
        agent_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        agent_public_key = agent_private_key.public_key()
        
        # Create certificate
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, agent_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "HomeConsole Agent"),
            x509.NameAttribute(NameOID.ORG_UNIT_NAME, agent_id),
        ])
        
        issuer = self._ca_cert.issuer
        
        now = datetime.now(timezone.utc)
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            agent_public_key
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            now
        ).not_valid_after(
            now + timedelta(days=valid_days)
        ).add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        ).add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        ).add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=True,
        ).sign(
            self._ca_private_key,
            hashes.SHA256(),
            backend=default_backend(),
        )
        
        return cert.public_bytes(serialization.Encoding.PEM)
    
    def verify_certificate(self, cert_pem: bytes) -> bool:
        """
        Verify a certificate was issued by this CA.
        
        Args:
            cert_pem: Certificate in PEM format
            
        Returns:
            True if valid and signed by this CA
        """
        try:
            cert = x509.load_pem_x509_certificate(
                cert_pem,
                backend=default_backend(),
            )
            
            # Verify signature using CA public key
            ca_public_key = self._ca_cert.public_key()
            ca_public_key.verify(
                cert.signature,
                cert.tbs_certificate_bytes,
                cert.signature_algorithm_oid,
            )
            
            # Check certificate is from our CA
            if cert.issuer != self._ca_cert.subject:
                return False
            
            # Check not expired
            now = datetime.now(timezone.utc)
            if now < cert.not_valid_before or now > cert.not_valid_after:
                return False
            
            return True
        except Exception:
            return False
    
    def get_certificate_common_name(self, cert_pem: bytes) -> str:
        """Extract common name from certificate."""
        try:
            cert = x509.load_pem_x509_certificate(
                cert_pem,
                backend=default_backend(),
            )
            cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            if cn:
                return cn[0].value
            return ""
        except Exception:
            return ""
    
    def get_agent_id_from_certificate(self, cert_pem: bytes) -> str:
        """Extract agent ID (OU) from certificate."""
        try:
            cert = x509.load_pem_x509_certificate(
                cert_pem,
                backend=default_backend(),
            )
            ou = cert.subject.get_attributes_for_oid(NameOID.ORG_UNIT_NAME)
            if ou:
                return ou[0].value
            return ""
        except Exception:
            return ""
