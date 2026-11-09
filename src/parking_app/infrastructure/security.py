"""Cryptographic utilities for password hashing and verification."""

from __future__ import annotations

import hashlib
import hmac
import os

_DEFAULT_ALGORITHM = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 600_000
_SALT_BYTES = 16


def hash_password(
    plain_password: str,
    iterations: int = _DEFAULT_ITERATIONS,
    salt: bytes | None = None,
) -> str:
    """Hash a plain text password using PBKDF2-HMAC-SHA256."""
    if not plain_password:
        raise ValueError("Mật khẩu không được để trống.")
    if salt is None:
        salt = os.urandom(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt,
        iterations,
    )
    salt_hex = salt.hex()
    hash_hex = derived.hex()
    return f"{_DEFAULT_ALGORITHM}${iterations}${salt_hex}${hash_hex}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against stored hash formatted as algorithm$iterations$salt$hash."""
    if not plain_password or not hashed_password:
        return False
    parts = hashed_password.split("$")
    if len(parts) != 4:
        return False
    algo, iter_str, salt_hex, expected_hex = parts
    if algo != _DEFAULT_ALGORITHM:
        return False
    try:
        iterations = int(iter_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
    except ValueError:
        return False
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(derived, expected)
