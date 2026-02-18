"""Secret generation utilities for credential rotation."""

import secrets
import string
from typing import Optional


def generate_strong_secret(length: int = 32, alphabet: Optional[str] = None) -> str:
    """
    Generate a cryptographically strong random secret.
    
    Uses secrets module (Python's CSPRNG) for high entropy.
    Default alphabet is alphanumeric + common special chars (URL-safe).
    
    Entropy calculation:
    - 32 chars from 94-char alphabet = ~200 bits entropy (sufficient)
    - 64 chars from 94-char alphabet = ~400 bits entropy (very strong)
    
    Args:
        length: Length of secret to generate (default: 32)
        alphabet: Custom alphabet to use (default: URL-safe alphanumeric)
    
    Returns:
        Cryptographically strong random string
    
    Raises:
        ValueError: if length < 8 (minimum entropy requirement)
    """
    if length < 8:
        raise ValueError("length must be >= 8 for sufficient entropy")
    
    if alphabet is None:
        # URL-safe alphabet: alphanumeric + hyphen + underscore
        # Avoids special chars that need escaping
        alphabet = string.ascii_letters + string.digits + "-_"
    
    # Use secrets.choice for each character (CSPRNG)
    secret = "".join(secrets.choice(alphabet) for _ in range(length))
    
    return secret


def generate_api_token(prefix: str = "cred", length: int = 48) -> str:
    """
    Generate an API token-style secret with prefix.
    
    Format: prefix_xxxxxxxxxxxx (where x is random alphanumeric)
    
    Args:
        prefix: Token prefix (usually shortened app name)
        length: Length of random part (default: 48)
    
    Returns:
        API token in format: prefix_randomstring
    """
    random_part = generate_strong_secret(length, string.ascii_letters + string.digits)
    return f"{prefix}_{random_part}"


def generate_database_password(length: int = 32) -> str:
    """
    Generate a database password-style secret.
    
    Includes uppercase, lowercase, digits, and special chars.
    (Many databases require special chars for security)
    
    Args:
        length: Length of password (default: 32)
    
    Returns:
        Database password with mixed character types
    """
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()_+-=[]{}|;:,.<>?"
    return generate_strong_secret(length, alphabet)


def calculate_entropy_bits(length: int, alphabet_size: int = 94) -> float:
    """
    Calculate entropy in bits for a generated secret.
    
    Formula: entropy = log2(alphabet_size ^ length)
    
    Args:
        length: Length of secret
        alphabet_size: Size of character alphabet (default: 94)
    
    Returns:
        Entropy in bits
    """
    import math
    if length <= 0 or alphabet_size <= 0:
        return 0.0
    return length * math.log2(alphabet_size)
