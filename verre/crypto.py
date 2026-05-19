"""Symmetric encryption helpers for storing Binance API credentials at rest.

We use Fernet (AES-128-CBC + HMAC-SHA256) from `cryptography`. The key is supplied
via the ``VERRE_ENCRYPTION_KEY`` environment variable. Generate one with::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(RuntimeError):
    """Raised when encryption or decryption fails."""


class Cipher:
    """Wrapper around Fernet that operates on str <-> str."""

    def __init__(self, key: str) -> None:
        if not key:
            raise EncryptionError(
                "VERRE_ENCRYPTION_KEY is empty. Generate one with "
                '`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.'
            )
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise EncryptionError(f"Invalid Fernet key: {exc}") from exc

    def encrypt(self, plaintext: str) -> str:
        token = self._fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise EncryptionError("Failed to decrypt: token invalid or key changed") from exc


def generate_key() -> str:
    """Generate a fresh Fernet key (for setup/CLI use)."""
    return Fernet.generate_key().decode("utf-8")
