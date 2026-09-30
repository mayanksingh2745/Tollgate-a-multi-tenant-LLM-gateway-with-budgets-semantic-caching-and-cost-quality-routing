import hashlib
import hmac
import secrets
from typing import Optional, Tuple

try:
    from argon2 import PasswordHasher

    _ph: Optional[PasswordHasher] = PasswordHasher()
except ImportError:
    _ph = None


def hash_password(password: str) -> str:
    """Hash password using Argon2id or SHA256 fallback if argon2-cffi is unavailable."""
    if _ph is not None:
        return _ph.hash(password)
    # Secure fallback algorithm using PBKDF2 HMAC SHA256 with 600,000 iterations
    salt = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
    return f"pbkdf2_sha256${salt.hex()}${key.hex()}"


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify password against stored hash."""
    if _ph is not None and hashed_password.startswith("$argon2"):
        try:
            return _ph.verify(hashed_password, password)
        except Exception:
            return False
    elif hashed_password.startswith("pbkdf2_sha256$"):
        try:
            _, salt_hex, key_hex = hashed_password.split("$")
            salt = bytes.fromhex(salt_hex)
            computed_key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
            return hmac.compare_digest(computed_key.hex(), key_hex)
        except Exception:
            return False
    return False


API_KEY_PREFIX = "tg_live_"
PREFIX_LENGTH = 16  # tg_live_ (8) + 8 hex chars = 16 chars total for database lookup prefix


def generate_api_key() -> Tuple[str, str, str]:
    """
    Generates a cryptographically secure API key.

    Returns:
        (raw_key, key_prefix, key_hash)

    Example:
        raw_key: "tg_live_a8f3d91c92b4e7..."
        key_prefix: "tg_live_a8f3d91c"
        key_hash: "3b7a8c..." (SHA256 hex string)
    """
    random_secret = secrets.token_urlsafe(32)  # 256 bits entropy
    raw_key = f"{API_KEY_PREFIX}{random_secret}"

    key_prefix = raw_key[:PREFIX_LENGTH]
    key_hash = hash_api_key(raw_key)

    return raw_key, key_prefix, key_hash


def hash_api_key(raw_key: str) -> str:
    """Compute SHA-256 hash of complete raw API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def verify_api_key_hash(raw_key: str, stored_hash: str) -> bool:
    """Constant-time comparison between raw API key hash and stored hash."""
    computed_hash = hash_api_key(raw_key)
    return hmac.compare_digest(computed_hash, stored_hash)


def resolve_client_ip(
    peer_ip: str,
    x_forwarded_for: Optional[str] = None,
    trusted_proxies: Optional[list[str]] = None,
) -> str:
    """
    Safely resolves the true client IP in a reverse-proxy topology.

    Never blindly trusts client-supplied headers (e.g. X-Forwarded-For).
    Only traverses X-Forwarded-For if the immediate peer_ip is present in trusted_proxies.
    Walks backwards from the rightmost proxy hop, returning the first non-trusted IP.
    """
    if not trusted_proxies:
        trusted_proxies = ["127.0.0.1", "::1"]

    if peer_ip not in trusted_proxies or not x_forwarded_for:
        return peer_ip

    # Parse comma-separated IPs from right to left
    hops = [ip.strip() for ip in x_forwarded_for.split(",") if ip.strip()]
    for hop in reversed(hops):
        if hop not in trusted_proxies:
            return hop

    return peer_ip
