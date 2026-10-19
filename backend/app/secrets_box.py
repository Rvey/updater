"""Reversible secret storage for the Affinebot link.

Stored form is self-describing: ``fernet:<token>`` when UPDATER_SECRET_KEY is set,
else ``plain:<secret>``. Rows written before a key was configured stay readable.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


class SecretBoxError(RuntimeError):
    pass


def _fernet() -> Fernet | None:
    key = (get_settings().updater_secret_key or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())  # a real Fernet key is used as is
    except ValueError:
        # any other string is stretched into a valid key
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def encrypt_secret(secret: str) -> str:
    box = _fernet()
    if box is None:
        return "plain:" + secret
    return "fernet:" + box.encrypt(secret.encode()).decode()


def decrypt_secret(stored: str) -> str:
    if stored.startswith("plain:"):
        return stored[len("plain:"):]
    if stored.startswith("fernet:"):
        box = _fernet()
        if box is None:
            raise SecretBoxError("UPDATER_SECRET_KEY is required to read this secret")
        try:
            return box.decrypt(stored[len("fernet:"):].encode()).decode()
        except InvalidToken as exc:
            raise SecretBoxError("UPDATER_SECRET_KEY does not match the stored secret") from exc
    raise SecretBoxError("Unknown secret format")
