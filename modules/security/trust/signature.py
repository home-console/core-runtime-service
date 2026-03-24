"""
Cryptographic signature verification using Ed25519.

Canonical security-domain implementation.
"""

import base64
import hashlib
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


class SignatureError(Exception):
    """Signature verification or generation failed."""
    pass


def generate_keypair() -> tuple[str, str]:
    """Generate a new Ed25519 keypair for plugin signing."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    return (
        base64.b64encode(private_bytes).decode("ascii"),
        base64.b64encode(public_bytes).decode("ascii"),
    )


def sign_message(message: bytes, private_key_b64: str) -> str:
    """Sign a message using Ed25519 private key."""
    try:
        private_bytes = base64.b64decode(private_key_b64)
        private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_bytes)
        signature = private_key.sign(message)
        return base64.b64encode(signature).decode("ascii")
    except Exception as e:
        raise SignatureError(f"Failed to sign message: {e}")


def verify_signature(message: bytes, public_key_b64: str, signature_b64: str) -> bool:
    """Verify a message signature using Ed25519 public key."""
    try:
        public_bytes = base64.b64decode(public_key_b64)
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(public_bytes)
        signature = base64.b64decode(signature_b64)

        public_key.verify(signature, message)
        return True
    except InvalidSignature:
        raise SignatureError("Signature verification failed: invalid signature")
    except Exception as e:
        raise SignatureError(f"Signature verification error: {e}")


def compute_payload_hash(manifest_json: str, archive_hash: str) -> bytes:
    """Compute the payload to be signed: (manifest + archive_hash)."""
    payload = (manifest_json + archive_hash).encode("utf-8")
    return payload


def compute_archive_sha256(file_path) -> str:
    """Compute SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()
