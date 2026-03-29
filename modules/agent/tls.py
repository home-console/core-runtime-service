"""
mTLS Support — CA and certificate generation.

Provides:
- CA certificate generation
- Agent certificate signing
- mTLS validation
"""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


class MTLSCertificateAuthority:
    """Certificate Authority for mTLS."""

    def __init__(self, ca_private_key_pem: bytes, ca_cert_pem: bytes):
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
        valid_days: int = 3650,
    ) -> tuple[bytes, bytes]:
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )

        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, common_name),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "HomeConsole"),
                x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            ]
        )

        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=valid_days))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=0),
                critical=True,
            )
            .add_extension(
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
            )
            .sign(
                private_key,
                hashes.SHA256(),
                backend=default_backend(),
            )
        )

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
        valid_days: int = 365,
    ) -> bytes:
        agent_private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend(),
        )
        agent_public_key = agent_private_key.public_key()

        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, agent_name),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "HomeConsole Agent"),
                x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, agent_id),
            ]
        )

        issuer = self._ca_cert.issuer

        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(agent_public_key)
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=valid_days))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
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
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=True,
            )
            .sign(
                cast(Any, self._ca_private_key),
                hashes.SHA256(),
                backend=default_backend(),
            )
        )

        return cert.public_bytes(serialization.Encoding.PEM)

    def verify_certificate(self, cert_pem: bytes) -> bool:
        try:
            cert = x509.load_pem_x509_certificate(
                cert_pem,
                backend=default_backend(),
            )

            ca_public_key = cast(Any, self._ca_cert.public_key())
            ca_public_key.verify(
                cert.signature,
                cert.tbs_certificate_bytes,
                padding.PKCS1v15(),
                cert.signature_hash_algorithm,
            )

            if cert.issuer != self._ca_cert.subject:
                return False

            now = datetime.now(timezone.utc)
            if now < cert.not_valid_before or now > cert.not_valid_after:
                return False

            return True
        except Exception:
            return False

    def get_certificate_common_name(self, cert_pem: bytes) -> str:
        try:
            cert = x509.load_pem_x509_certificate(
                cert_pem,
                backend=default_backend(),
            )
            cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
            if cn:
                return str(cn[0].value)
            return ""
        except Exception:
            return ""

    def get_agent_id_from_certificate(self, cert_pem: bytes) -> str:
        try:
            cert = x509.load_pem_x509_certificate(
                cert_pem,
                backend=default_backend(),
            )
            ou = cert.subject.get_attributes_for_oid(NameOID.ORGANIZATIONAL_UNIT_NAME)
            if ou:
                return str(ou[0].value)
            return ""
        except Exception:
            return ""
