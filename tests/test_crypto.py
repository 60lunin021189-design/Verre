"""Tests for the crypto module."""

from __future__ import annotations

import pytest

from verre.crypto import Cipher, EncryptionError, generate_key


def test_roundtrip() -> None:
    cipher = Cipher(generate_key())
    token = cipher.encrypt("hello world")
    assert token != "hello world"
    assert cipher.decrypt(token) == "hello world"


def test_empty_key_rejected() -> None:
    with pytest.raises(EncryptionError):
        Cipher("")


def test_invalid_key_rejected() -> None:
    with pytest.raises(EncryptionError):
        Cipher("not-a-fernet-key")


def test_decrypt_wrong_key_fails() -> None:
    c1 = Cipher(generate_key())
    c2 = Cipher(generate_key())
    token = c1.encrypt("secret")
    with pytest.raises(EncryptionError):
        c2.decrypt(token)
