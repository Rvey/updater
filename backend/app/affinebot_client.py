"""Typed client for the Affinebot link API (shared contract v1).

Auth on every call: ``Authorization: Bearer <secret>`` and ``X-Link-Client: <client_id>``.
All methods return the decoded JSON dict and raise :class:`AffinebotError` on failure.

Public names for other sessions:
  AffinebotClient, AffinebotError, client_for_workspace, http_error_for,
  invalidate (per client_id cache drop), _transport_override (test hook), _cache.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import get_settings
from .db import AffinebotLink
from .secrets_box import SecretBoxError, decrypt_secret

# Tests (and other sessions' tests) set this to an httpx.MockTransport; it wins over everything.
_transport_override: httpx.BaseTransport | None = None

ITEMS_TTL_S = 60.0
REPOS_TTL_S = 300.0


class AffinebotError(Exception):
    """Failure talking to Affinebot.

    ``status``: upstream HTTP status, or 502 for unreachable/rejected/upstream, 404 for not linked.
    ``detail`` is a stable code or Affinebot's own detail string; it never contains the secret.
    """

    def __init__(self, status: int, detail: str, retry_after: str | None = None):
        super().__init__(f"{status} {detail}")
        self.status = status
        self.detail = detail
        self.retry_after = retry_after


def http_error_for(exc: AffinebotError) -> HTTPException:
    """Updater error map: unreachable/rejected/upstream -> 502, 403/404 pass through, 429 -> 503 + Retry-After."""
    if exc.status == 429:
        headers = {"Retry-After": exc.retry_after} if exc.retry_after else None
        return HTTPException(status_code=503, detail=exc.detail or "affinebot_rate_limited", headers=headers)
    if exc.status in (403, 404):
        return HTTPException(status_code=exc.status, detail=exc.detail)
    return HTTPException(status_code=502, detail=exc.detail)


class TTLCache:
    """Tiny in-process cache. ``clock`` is injectable so tests can advance time."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self._data: dict[tuple, tuple[float, Any]] = {}

    def get(self, key: tuple) -> Any | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        if hit[0] <= self.clock():
            self._data.pop(key, None)
            return None
        return hit[1]

    def set(self, key: tuple, value: Any, ttl: float) -> None:
        self._data[key] = (self.clock() + ttl, value)

    def invalidate(self, client_id: str) -> None:
        """Drop every entry whose key starts with this client_id."""
        for key in [k for k in self._data if k[0] == client_id]:
            self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()


_cache = TTLCache()


def invalidate(client_id: str) -> None:
    _cache.invalidate(client_id)


def _detail_of(response: httpx.Response, fallback: str) -> str:
    try:
        body = response.json()
    except ValueError:
        return fallback
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail[:300] if isinstance(detail, str) and detail else fallback


class AffinebotClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        secret: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self._secret = secret
        self._transport = _transport_override or transport
        self.timeout = timeout if timeout is not None else get_settings().affinebot_timeout_s

    # --- plumbing ------------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._secret}", "X-Link-Client": self.client_id}

    def _request(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> Any:
        headers = self._headers()
        try:
            with httpx.Client(transport=self._transport, timeout=self.timeout, follow_redirects=False) as http:
                response = http.request(method, self.base_url + path, params=params, json=json, headers=headers)
        except httpx.HTTPError:
            raise AffinebotError(502, "affinebot_unreachable") from None
        status = response.status_code
        if status == 401:
            raise AffinebotError(502, "affinebot_rejected")
        if status == 429:
            raise AffinebotError(429, _detail_of(response, "affinebot_rate_limited"), response.headers.get("Retry-After"))
        if status in (403, 404):
            raise AffinebotError(status, _detail_of(response, "forbidden" if status == 403 else "not_found"))
        if status >= 500:
            raise AffinebotError(502, "affinebot_upstream")
        if status >= 400:
            raise AffinebotError(status, _detail_of(response, "affinebot_error"))
        try:
            return response.json()
        except ValueError:
            raise AffinebotError(502, "affinebot_upstream") from None

    # --- contract methods ----------------------------------------------------------------

    def health(self) -> dict:
        """GET /link/v1/health -> {ok, app, version, github_app, redis, db, client:{client_id, owner, installation_id}}."""
        return self._request("GET", "/link/v1/health")

    def repos(self, *, refresh: bool = False) -> dict:
        """GET /link/v1/repos -> {owner, installation_id, repos:[{full_name, private, default_branch}]}. Cached 300s."""
        key = (self.client_id, "repos")
        if not refresh:
            cached = _cache.get(key)
            if cached is not None:
                return cached
        data = self._request("GET", "/link/v1/repos")
        _cache.set(key, data, REPOS_TTL_S)
        return data

    def items(self, repo: str, kind: str = "all", state: str = "open", page: int = 1, per_page: int = 50) -> dict:
        """GET /link/v1/repos/{owner}/{name}/items -> {items:[{number, title, body, state, merged, draft, url,
        author, assignees, labels, comments, is_pr, updated_at, branch}], next_page}. Cached 60s."""
        owner, _, name = repo.partition("/")
        if not owner or not name or "/" in name:
            raise AffinebotError(404, "not_found")
        key = (self.client_id, "items", repo.lower(), kind, state, page, per_page)
        cached = _cache.get(key)
        if cached is not None:
            return cached
        data = self._request(
            "GET",
            f"/link/v1/repos/{owner}/{name}/items",
            params={"kind": kind, "state": state, "page": page, "per_page": per_page},
        )
        _cache.set(key, data, ITEMS_TTL_S)
        return data


class AffinebotAdminClient(AffinebotClient):
    """Server-level admin calls (managed mode). Same timeout, error map and transport hook as the runtime client.

    The admin token is only ever sent as the Authorization header; it is never put in errors or logs.
    """

    def __init__(self, base_url: str, admin_token: str, transport: httpx.BaseTransport | None = None, timeout: float | None = None):
        super().__init__(base_url, "", admin_token, transport=transport, timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._secret}"}

    def admin_owners(self) -> dict:
        """GET /link/admin/owners -> {owners:[{owner, installation_id, installed}]}."""
        return self._request("GET", "/link/admin/owners")

    def admin_mint(self, client_id: str, label: str, owner: str) -> dict:
        """POST /link/admin/clients (rotate=true) -> {client_id, token, owner, installation_id}."""
        return self._request(
            "POST",
            "/link/admin/clients",
            json={"client_id": client_id, "label": label, "owner": owner, "rotate": True},
        )

    def admin_revoke(self, client_id: str) -> None:
        """DELETE /link/admin/clients/{client_id}; 404 (unknown client) surfaces as AffinebotError."""
        self._request("DELETE", f"/link/admin/clients/{client_id}")


def managed_mode() -> bool:
    settings = get_settings()
    return bool(settings.affinebot_url.strip() and settings.affinebot_admin_token.strip())


def admin_client() -> AffinebotAdminClient:
    settings = get_settings()
    return AffinebotAdminClient(settings.affinebot_url.strip(), settings.affinebot_admin_token.strip())


def client_for_workspace(db: Session, workspace_id: str, transport: httpx.BaseTransport | None = None) -> AffinebotClient:
    """Build a client from the workspace's stored link; AffinebotError(404, 'affinebot_not_linked') if none."""
    link = db.query(AffinebotLink).filter(AffinebotLink.workspace_id == workspace_id).first()
    if link is None:
        raise AffinebotError(404, "affinebot_not_linked")
    try:
        secret = decrypt_secret(link.secret_enc)
    except SecretBoxError:
        raise AffinebotError(502, "affinebot_secret_unreadable") from None
    return AffinebotClient(link.base_url, link.client_id, secret, transport=transport)
