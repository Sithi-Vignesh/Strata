"""Focused Argon2id password primitives for future authentication flows."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
_PASSWORD_HASHER = PasswordHasher()


def validate_password(password: str) -> str:
    """Validate the frozen product password policy without changing the value."""
    if not isinstance(password, str):
        raise ValueError("password must be a string.")
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"password must contain between {MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH} characters."
        )
    if password.isspace():
        raise ValueError("password must not be whitespace only.")
    return password


def hash_password(password: str) -> str:
    """Return an Argon2id encoded password hash after policy validation."""
    return _PASSWORD_HASHER.hash(validate_password(password))


def verify_password(encoded_hash: str, password: str) -> bool:
    """Return whether a password verifies, without leaking invalid-hash details."""
    if not isinstance(encoded_hash, str) or not isinstance(password, str):
        return False
    try:
        return _PASSWORD_HASHER.verify(encoded_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def needs_rehash(encoded_hash: str) -> bool:
    """Return whether a valid Argon2 hash needs replacement under current settings."""
    if not isinstance(encoded_hash, str):
        return False
    try:
        return _PASSWORD_HASHER.check_needs_rehash(encoded_hash)
    except (InvalidHashError, VerificationError):
        return False
