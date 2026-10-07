"""Focused coverage for the P1B-A Argon2id password adapter."""

import pytest

from strata_backend.product_passwords import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)


def test_password_adapter_hashes_verifies_and_wraps_rehash_check() -> None:
    password = "correct horse battery staple"
    encoded = hash_password(password)

    assert encoded != password
    assert encoded.startswith("$argon2id$")
    assert verify_password(encoded, password)
    assert not verify_password(encoded, "wrong password")
    assert not verify_password("not-an-argon2-hash", password)
    assert needs_rehash(encoded) is False
    assert needs_rehash("not-an-argon2-hash") is False


def test_password_policy_boundaries() -> None:
    assert validate_password("a" * MIN_PASSWORD_LENGTH) == "a" * MIN_PASSWORD_LENGTH
    assert validate_password("a" * MAX_PASSWORD_LENGTH) == "a" * MAX_PASSWORD_LENGTH
    for password in ("a" * (MIN_PASSWORD_LENGTH - 1), "a" * (MAX_PASSWORD_LENGTH + 1), " " * MIN_PASSWORD_LENGTH):
        with pytest.raises(ValueError):
            validate_password(password)
