"""Email + password login and per-user API keys.

Backward compatible: the legacy UPDATER_TOKEN env bearer still works.
New tokens:
- session tokens: ups_<secret>, sha256-hashed in user_sessions
- api keys: upk_<secret>, sha256-hashed in api_keys, shown once at creation
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

API_KEY_PREFIX = "upk_"
SESSION_PREFIX = "ups_"
SESSION_TTL_DAYS = 30
_PBKDF2_ITERATIONS = 200000


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return "pbkdf2$" + str(_PBKDF2_ITERATIONS) + "$" + salt.hex() + "$" + dk.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def _new_secret() -> str:
    return secrets.token_urlsafe(32)


def new_api_key():
    secret = _new_secret()
    key = API_KEY_PREFIX + secret
    digest = hashlib.sha256(key.encode()).hexdigest()
    return key, digest, key[:12]


def new_session_token():
    secret = _new_secret()
    token = SESSION_PREFIX + secret
    digest = hashlib.sha256(token.encode()).hexdigest()
    return token, digest


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def session_expiry():
    return datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
