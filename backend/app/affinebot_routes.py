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
from .schemas import AffinebotLinkRead, AffinebotLinkWrite
from .secrets_box import encrypt_secret

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


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
    db.delete(link)
    db.commit()
    return Response(status_code=204)
