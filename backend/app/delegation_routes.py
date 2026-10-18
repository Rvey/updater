"""Delegate a task to Claude Code through Affinebot: start, list, poll, cancel and the signed status callback."""

from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import affinebot_client as ab
from . import workspaces as ws
from .affinebot_client import AffinebotError
from .config import get_settings
from .db import Delegation, Project, Task, User, get_db, now_utc
from .github_sync import GitHubSyncError, parse_repo, verify_signature
from .main import _column_size, _current_user, _reindex_task_column, require_token
from .schemas import DelegateRequest, DelegationRead

router = APIRouter(prefix="/api")

ACTIVE = ("queued", "running")
RANK = {"queued": 0, "running": 1, "pr_opened": 2, "failed": 2}
STALE_AFTER = timedelta(seconds=60)
_EXTERNAL_RE = re.compile(r"^github:([^#\s]+/[^#\s]+)#(\d+)$")


def _clip(value, limit: int) -> str | None:
    return None if value is None else str(value)[:limit]


def _task_for(db: Session, user: User, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None or not ws.row_visible(db, task, user.id):
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _delegation_for(db: Session, user: User, delegation_id: str) -> tuple[Delegation, Task]:
    row = db.get(Delegation, delegation_id)
    task = db.get(Task, row.task_id) if row is not None else None
    if row is None or task is None or not ws.row_visible(db, task, user.id):
        raise HTTPException(status_code=404, detail="Delegation not found")
    return row, task


def _repo_target(task: Task) -> tuple[str, int | None]:
    match = _EXTERNAL_RE.match(task.external_id or "")
    if match:
        return match.group(1).lower(), int(match.group(2))
    if task.repo_url and "github.com" in task.repo_url.lower():
        try:
            owner, name = parse_repo(task.repo_url)
            return f"{owner}/{name}".lower(), None
        except GitHubSyncError:
            pass
    raise HTTPException(status_code=422, detail="task has no GitHub repo")


def _pr_url_ok(repo: str, url: str) -> bool:
    return re.fullmatch(rf"https://github\.com/{re.escape(repo)}/pull/\d+", url, re.I) is not None


def _is_terminal(row: Delegation) -> bool:
    return row.status in ("pr_opened", "failed", "cancelled")


def _move_task_to_review(db: Session, row: Delegation) -> None:
    task = db.get(Task, row.task_id)
    if task is None:
        return
    previous = task.status
    if not task.external_url:
        task.external_url = row.pr_url
    tags = list(task.tags or [])
    if "claude-code" not in tags:
        task.tags = [*tags, "claude-code"]
    if previous != "review":
        task.status = "review"
        task.position = int(_column_size(db, "review", task.project_id))
        task.completed_at = None
    db.flush()
    _reindex_task_column(db, "review", task.project_id)
    if previous != "review":
        _reindex_task_column(db, previous, task.project_id)


def apply_status(
    db: Session, row: Delegation, status: str, *, branch=None, pr_url=None, pr_number=None, error=None, summary=None,
) -> bool:
    """Forward-only transition (queued < running < pr_opened|failed; cancelled is terminal). True when applied."""
    if _is_terminal(row) or RANK.get(status, -1) <= RANK.get(row.status, 0):
        return False
    now = now_utc()
    row.status = status
    if branch:
        row.branch = _clip(branch, 255)
    if summary is not None:
        row.summary = _clip(summary, 4000)
    if status == "running":
        row.started_at = row.started_at or now
    else:
        row.finished_at = now
        row.started_at = row.started_at or now
        if status == "pr_opened":
            row.pr_url = _clip(pr_url, 600)
            row.pr_number = pr_number
            row.error = None
        else:
            row.error = _clip(error, 2000) or "failed"
    row.updated_at = now
    db.flush()
    if status == "pr_opened":
        _move_task_to_review(db, row)
    db.commit()
    return True


BRANCH_PREFIX = "affinebot/claude-"  # must match Affinebot worker.claude_code_job


def apply_pr_webhook(db: Session, payload: dict) -> None:
    """GitHub pull_request 'opened' from an Affinebot branch (affinebot/claude-<remote_id[:8]>) fills in a delegation whose callback was lost."""
    try:
        if payload.get("action") != "opened":
            return
        pull = payload.get("pull_request") or {}
        ref = str((pull.get("head") or {}).get("ref") or "")
        repo = str((payload.get("repository") or {}).get("full_name") or "").lower()
        url = str(pull.get("html_url") or "")
        if not ref.startswith(BRANCH_PREFIX) or not repo or not _pr_url_ok(repo, url):
            return
        rows = db.scalars(
            select(Delegation).where(Delegation.repo == repo, Delegation.status.in_(("queued", "running", "failed")))
            .order_by(Delegation.created_at.desc())
        ).all()
        for row in rows:
            if row.branch == ref or (row.remote_id and ref == f"{BRANCH_PREFIX}{row.remote_id[:8]}"):
                row.status = "running"  # let a recovered 'failed' row advance
                apply_status(db, row, "pr_opened", branch=ref, pr_url=url, pr_number=pull.get("number"))
                return
    except Exception:  # a delegation hint must never break the main webhook
        db.rollback()


def _client_for_project(db: Session, project_id: str | None):
    project = db.get(Project, project_id) if project_id else None
    if project is None:
        raise HTTPException(status_code=422, detail="task has no project")
    try:
        return ab.client_for_workspace(db, project.workspace_id)
    except AffinebotError as exc:
        if exc.status == 404 and exc.detail == "affinebot_not_linked":
            raise HTTPException(status_code=409, detail="affinebot_not_linked") from None
        raise ab.http_error_for(exc) from None


@router.post("/tasks/{task_id}/delegate", response_model=DelegationRead, status_code=201, dependencies=[Depends(require_token)])
def delegate_task(task_id: str, payload: DelegateRequest | None = None, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    payload = payload or DelegateRequest()
    task = _task_for(db, user, task_id)
    existing = db.scalar(
        select(Delegation).where(Delegation.task_id == task.id, Delegation.status.in_(ACTIVE))
        .order_by(Delegation.created_at.desc())
    )
    if existing is not None:
        return existing
    repo, issue_number = _repo_target(task)
    public_url = get_settings().updater_public_url.strip().rstrip("/")
    if not public_url:
        raise HTTPException(status_code=503, detail="updater_public_url_not_configured")
    client = _client_for_project(db, task.project_id)
    parts = [task.title.strip(), (task.description or "").strip(), (payload.instruction or "").strip()]
    row = Delegation(
        user_id=user.id, project_id=task.project_id, task_id=task.id, repo=repo, issue_number=issue_number,
        instruction="\n\n".join(p for p in parts if p)[:12000],
        base_branch=(payload.base_branch or "").strip() or None, status="queued",
    )
    db.add(row)
    db.commit()  # commit first: Affinebot may call back before create_delegation returns
    db.refresh(row)
    body = {
        "delegation_id": row.id, "repo": repo, "issue_number": issue_number, "title": task.title,
        "instruction": row.instruction, "base_branch": row.base_branch,
        "callback_url": f"{public_url}/api/delegations/{row.id}/status",
    }
    try:
        data = client.create_delegation(body)
        remote_id = _clip((data or {}).get("remote_id"), 64)
        if not remote_id:
            raise AffinebotError(502, "affinebot_upstream")
    except AffinebotError as exc:
        db.refresh(row)
        if row.status in ACTIVE:
            row.status, row.error, row.finished_at = "failed", _clip(exc.detail, 2000), now_utc()
            db.commit()
        db.refresh(row)
        return row
    db.refresh(row)  # a callback may have advanced it meanwhile
    row.remote_id = remote_id
    db.commit()
    db.refresh(row)
    return row


@router.get("/tasks/{task_id}/delegations", response_model=list[DelegationRead], dependencies=[Depends(require_token)])
def list_delegations(task_id: str, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    task = _task_for(db, user, task_id)
    return list(db.scalars(
        select(Delegation).where(Delegation.task_id == task.id).order_by(Delegation.created_at.desc(), Delegation.id)
    ).all())


def _refresh_remote(db: Session, row: Delegation) -> None:
    """Fallback for lost callbacks: poll Affinebot, forward-only, errors swallowed."""
    row.updated_at = now_utc()  # throttle: at most one poll per minute per row
    db.commit()
    try:
        client = _client_for_project(db, row.project_id)
        remote = client.get_delegation(row.remote_id)
    except (AffinebotError, HTTPException):
        return
    status = remote.get("status")
    pr_url = remote.get("pr_url")
    if status == "pr_opened" and not (pr_url and _pr_url_ok(row.repo, pr_url)):
        return
    if status in RANK:
        apply_status(
            db, row, status, branch=remote.get("branch"), pr_url=pr_url, pr_number=remote.get("pr_number"),
            error=remote.get("error"), summary=remote.get("summary"),
        )


@router.get("/delegations/{delegation_id}", response_model=DelegationRead, dependencies=[Depends(require_token)])
def get_delegation(delegation_id: str, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    row, _ = _delegation_for(db, user, delegation_id)
    updated = ws.aware(row.updated_at)
    if row.status in ACTIVE and row.remote_id and updated is not None and now_utc() - updated > STALE_AFTER:
        _refresh_remote(db, row)
        db.refresh(row)
    return row


@router.post("/delegations/{delegation_id}/cancel", response_model=DelegationRead, dependencies=[Depends(require_token)])
def cancel_delegation(delegation_id: str, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    row, _ = _delegation_for(db, user, delegation_id)
    if row.status not in ACTIVE:
        return row
    if row.remote_id:
        try:
            _client_for_project(db, row.project_id).cancel_delegation(row.remote_id)
        except (AffinebotError, HTTPException):
            pass  # best effort; the local state is what the user asked for
    db.refresh(row)
    if row.status in ACTIVE:
        now = now_utc()
        row.status, row.finished_at, row.updated_at = "cancelled", now, now
        db.commit()
        db.refresh(row)
    return row


class _Callback(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    branch: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    error: str | None = None
    summary: str | None = None


@router.post("/delegations/{delegation_id}/status", response_model=DelegationRead)
async def delegation_callback(delegation_id: str, request: Request, db: Session = Depends(get_db)):
    """Affinebot -> updater. Not behind require_token: the HMAC signature is the only credential."""
    secret = get_settings().affinebot_callback_secret
    if not secret:
        raise HTTPException(status_code=503, detail="affinebot_callback_secret_not_configured")
    body = await request.body()
    if not verify_signature(secret, body, request.headers.get("x-affinebot-signature")):
        raise HTTPException(status_code=401, detail="Invalid signature")
    row = db.get(Delegation, delegation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Delegation not found")
    try:
        data = _Callback.model_validate_json(body)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Malformed callback body") from None
    if data.status not in ("running", "pr_opened", "failed"):
        raise HTTPException(status_code=422, detail="status must be running, pr_opened or failed")
    if data.pr_url is not None or data.status == "pr_opened":
        if not data.pr_url or not _pr_url_ok(row.repo, data.pr_url):
            raise HTTPException(status_code=422, detail=f"pr_url must be https://github.com/{row.repo}/pull/<n>")
    apply_status(
        db, row, data.status, branch=data.branch, pr_url=data.pr_url, pr_number=data.pr_number,
        error=data.error, summary=data.summary,
    )
    db.refresh(row)
    return row
