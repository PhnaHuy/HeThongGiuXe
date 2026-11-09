"""Unit tests for password hashing and verification."""

import pytest

from parking_app.infrastructure.security import hash_password, verify_password


def test_hash_and_verify_password_success() -> None:
    plain = "MySecurePassword123"
    hashed = hash_password(plain, iterations=10_000)  # Lower iterations for fast test
    assert hashed.startswith("pbkdf2_sha256$10000$")
    assert verify_password(plain, hashed) is True


def test_verify_password_incorrect_fails() -> None:
    hashed = hash_password("CorrectPassword", iterations=10_000)
    assert verify_password("WrongPassword", hashed) is False


def test_verify_password_empty_or_malformed() -> None:
    assert verify_password("", "some_hash") is False
    assert verify_password("pwd", "") is False
    assert verify_password("pwd", "invalid_hash_structure") is False
    assert verify_password("pwd", "pbkdf2_sha256$invalid$salt$hash") is False


def test_hash_password_empty_raises() -> None:
    with pytest.raises(ValueError, match="không được để trống"):
        hash_password("")
