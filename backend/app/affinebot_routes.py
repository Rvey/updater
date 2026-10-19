"""Per-workspace Affinebot link: store, test, read, remove. The secret never leaves the server."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import affinebot_client as ab
from . import workspaces as ws
from .affinebot_client import AffinebotError
from .db import AffinebotLink, User, get_db, now_utc
from .main import _current_user, require_token
from .config import get_settings
from .schemas import AffinebotConnect, AffinebotLinkRead, AffinebotLinkWrite
from .secrets_box import encrypt_secret

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


OWNERS_TTL_S = 60.0
_OWNERS_KEY = ("__admin__", "owners")


def _clean_base_url(value: str) -> str:
    raw = (value or "").strip()
    try:
        parts = urlsplit(raw)
        port = parts.port  # raises on a bad port
    except ValueError:
        raise HTTPException(status_code=422, detail="base_url is not a valid URL") from None
    del port
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise HTTPException(status_code=422, detail="base_url must be an http(s) URL")
    if parts.username or parts.password or parts.fragment:
        raise HTTPException(status_code=422, detail="base_url must not contain credentials or a fragment")
    if parts.query:
        raise HTTPException(status_code=422, detail="base_url must not contain a query string")
    return raw.rstrip("/")


def _get_link(db: Session, workspace_id: str) -> AffinebotLink | None:
    return db.scalars(select(AffinebotLink).where(AffinebotLink.workspace_id == workspace_id)).first()


def _read(link: AffinebotLink) -> AffinebotLinkRead:
    return AffinebotLinkRead.model_validate(link)


def run_check(db: Session, link: AffinebotLink) -> AffinebotLink:
    """Call health then repos; record status/owner/installation/last_error on the row. Never raises."""
    link.last_checked_at = now_utc()
    try:
        client = ab.client_for_workspace(db, link.workspace_id)
        ab.invalidate(link.client_id)
        health = client.health()
        if not health.get("ok"):
            raise AffinebotError(502, "affinebot_unhealthy")
        info = health.get("client") or {}
        repos = client.repos(refresh=True)
        link.github_owner = (repos.get("owner") or info.get("owner") or None)
        installation = repos.get("installation_id", info.get("installation_id"))
        link.installation_id = installation if isinstance(installation, int) else None
        link.status, link.last_error = "active", None
    except AffinebotError as exc:
        link.status, link.last_error = "error", exc.detail[:300]
    db.commit()
    db.refresh(link)
    return link


@router.get("/affinebot/config")
def affinebot_config(user: User = Depends(_current_user)):
    """Managed-mode info for the UI. The admin token is never included."""
    if not ab.managed_mode():
        return {"managed": False, "base_url": None, "owners": []}
    base_url = get_settings().affinebot_url.strip().rstrip("/")
    owners = ab._cache.get(_OWNERS_KEY)
    if owners is None:
        try:
            data = ab.admin_client().admin_owners()
        except AffinebotError:
            return {"managed": True, "base_url": base_url, "owners": [], "error": "affinebot_unreachable"}
        rows = data.get("owners") if isinstance(data, dict) else None
        owners = [
            {"owner": str(row["owner"]), "installed": bool(row.get("installed"))}
            for row in (rows if isinstance(rows, list) else [])
            if isinstance(row, dict) and row.get("owner")
        ]
        ab._cache.set(_OWNERS_KEY, owners, OWNERS_TTL_S)
    return {"managed": True, "base_url": base_url, "owners": owners}


@router.post("/workspaces/{workspace_id}/affinebot/connect", response_model=AffinebotLinkRead)
def connect_link(
    workspace_id: str,
    payload: AffinebotConnect,
    db: Session = Depends(get_db),
    user: User = Depends(_current_user),
):
    workspace, _ = ws.require_workspace_owner(db, user, workspace_id)
    if not ab.managed_mode():
        raise HTTPException(status_code=409, detail="affinebot_not_managed")
    owner = payload.owner.strip()
    if not owner:
        raise HTTPException(status_code=422, detail="owner is required")
    try:
        minted = ab.admin_client().admin_mint(workspace_id, f"updater:{workspace.name}"[:100], owner)
    except AffinebotError as exc:
        if exc.status == 403:
            raise HTTPException(status_code=403, detail="owner_not_allowed") from None
        if exc.status == 404:
            if exc.detail == "github_app_not_installed":
                raise HTTPException(status_code=422, detail="github_app_not_installed") from None
            raise HTTPException(status_code=502, detail="affinebot_upstream") from None
        raise ab.http_error_for(exc) from None
    token = minted.get("token") if isinstance(minted, dict) else None
    if not isinstance(token, str) or not token:
        raise HTTPException(status_code=502, detail="affinebot_upstream")
    link = _get_link(db, workspace_id)
    if link is None:
        link = AffinebotLink(workspace_id=workspace_id, base_url="", client_id=workspace_id, secret_enc="")
        db.add(link)
    else:
        ab.invalidate(link.client_id)
    link.base_url = get_settings().affinebot_url.strip().rstrip("/")
    link.client_id = workspace_id
    link.secret_enc = encrypt_secret(token)
    link.status, link.last_error, link.github_owner, link.installation_id = "pending", None, None, None
    db.commit()
    return _read(run_check(db, link))


@router.put("/workspaces/{workspace_id}/affinebot", response_model=AffinebotLinkRead)
def put_link(
    workspace_id: str,
    payload: AffinebotLinkWrite,
    db: Session = Depends(get_db),
    user: User = Depends(_current_user),
):
    ws.require_workspace_owner(db, user, workspace_id)
    base_url = _clean_base_url(payload.base_url)
    secret = payload.secret.get_secret_value().strip()
    client_id = payload.client_id.strip()
    if not secret or not client_id:
        raise HTTPException(status_code=422, detail="client_id and secret are required")
    link = _get_link(db, workspace_id)
    if link is None:
        link = AffinebotLink(workspace_id=workspace_id, base_url=base_url, client_id=client_id, secret_enc="")
        db.add(link)
    else:
        ab.invalidate(link.client_id)
    link.base_url, link.client_id = base_url, client_id
    link.secret_enc = encrypt_secret(secret)
    link.status, link.last_error, link.github_owner, link.installation_id = "pending", None, None, None
    db.commit()
    return _read(run_check(db, link))


@router.get("/workspaces/{workspace_id}/affinebot", response_model=AffinebotLinkRead)
def get_link(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    ws.require_workspace_member(db, user, workspace_id)
    link = _get_link(db, workspace_id)
    if link is None:
        raise HTTPException(status_code=404, detail="affinebot_not_linked")
    return _read(link)


@router.post("/workspaces/{workspace_id}/affinebot/check", response_model=AffinebotLinkRead)
def check_link(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    ws.require_workspace_member(db, user, workspace_id)
    link = _get_link(db, workspace_id)
    if link is None:
        raise HTTPException(status_code=404, detail="affinebot_not_linked")
    return _read(run_check(db, link))


@router.delete("/workspaces/{workspace_id}/affinebot", status_code=204)
def delete_link(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    ws.require_workspace_owner(db, user, workspace_id)
    link = _get_link(db, workspace_id)
    if link is None:
        raise HTTPException(status_code=404, detail="affinebot_not_linked")
    ab.invalidate(link.client_id)
    if ab.managed_mode() and link.client_id == workspace_id:
        try:
            ab.admin_client().admin_revoke(workspace_id)
        except AffinebotError:
            pass  # best effort: the local link is removed regardless
    db.delete(link)
    db.commit()
    return Response(status_code=204)
