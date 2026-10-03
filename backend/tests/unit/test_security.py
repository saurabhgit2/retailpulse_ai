"""Password hashing and tokens."""

from __future__ import annotations

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hashing_is_one_way_and_salted():
    first = hash_password("a long test passphrase")
    second = hash_password("a long test passphrase")
    assert first != second          # different salt each time
    assert "passphrase" not in first
    assert verify_password("a long test passphrase", first)
    assert verify_password("a long test passphrase", second)


def test_the_wrong_password_fails_and_a_broken_hash_does_not_crash():
    stored = hash_password("correct horse battery")
    assert verify_password("wrong password here", stored) is False
    assert verify_password("anything", "not-a-hash") is False


def test_token_round_trip_carries_the_subject():
    token, expires_in = create_access_token("user-123")
    assert expires_in == get_settings().jwt_expire_minutes * 60
    assert decode_access_token(token)["sub"] == "user-123"


def test_a_token_signed_with_another_key_is_rejected():
    forged = jwt.encode({"sub": "someone-else", "exp": 9999999999}, "other-key", algorithm="HS256")
    assert decode_access_token(forged) is None


def test_an_expired_token_is_rejected(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "jwt_expire_minutes", -1)  # already expired
    token, _ = create_access_token("user-123")
    assert decode_access_token(token) is None


@pytest.mark.parametrize("bad", ["", "not.a.token", "a.b.c"])
def test_rubbish_tokens_are_rejected(bad):
    assert decode_access_token(bad) is None
