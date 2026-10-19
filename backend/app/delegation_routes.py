"""Delegate a task to the assigning user's own coding agent: queue, list, claim, report and cancel."""

from __future__ import annotations

import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import workspaces as ws
from .db import Delegation, Task, User, get_db, now_utc
from .github_sync import GitHubSyncError, parse_repo
from .main import _column_size, _current_user, _reindex_task_column, require_token
from .schemas import DelegateRequest, DelegationClaim, DelegationRead, DelegationReport

router = APIRouter(prefix="/api")

ACTIVE = ("queued", "running")
RANK = {"queued": 0, "running": 1, "pr_opened": 2, "failed": 2}
STALE_AFTER = timedelta(minutes=30)  # a running claim can be taken over after this
_EXTERNAL_RE = re.compile(r"^github:([^#\s]+/[^#\s]+)#(\d+)$")


def _clip(value, limit: int) -> str | None:
    return None if value is None else str(value)[:limit]


def _task_for(db: Session, user: User, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None or not ws.row_visible(db, task, user.id):
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _suggested_branch(row: Delegation) -> str:
    return f"{BRANCH_PREFIX}{row.id[:8]}"


def _read(db: Session, row: Delegation) -> DelegationRead:
    task = db.get(Task, row.task_id)
    data = DelegationRead.model_validate(row)
    data.task_title = task.title if task else None
    data.task_description = task.description if task else None
    ext = (task.external_url or "") if task else ""
    if "github.com" in ext.lower() and "/issues/" in ext:
        data.issue_url = ext
    elif row.issue_number:
        data.issue_url = f"https://github.com/{row.repo}/issues/{row.issue_number}"
    data.suggested_branch = _suggested_branch(row)
    return data


def _repo_key(value: str) -> str:
    """owner/name (lowercase) from a GitHub URL, SSH remote or bare owner/name."""
    cleaned = ws.normalize_repo_url(value)
    for prefix in ("https://github.com/", "github.com/"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    return cleaned.strip("/")


def _own_delegation(db: Session, user: User, delegation_id: str) -> Delegation:
    row = db.get(Delegation, delegation_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Delegation not found")
    return row


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


BRANCH_PREFIX = "updater/delegation-"  # suggested_branch = prefix + delegation id[:8]


def apply_pr_webhook(db: Session, payload: dict) -> None:
    """GitHub pull_request 'opened' from an updater/delegation-<id[:8]> branch fills in a delegation whose report was lost."""
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
            if row.branch == ref or ref == _suggested_branch(row):
                row.status = "running"  # let a recovered 'failed' row advance
                apply_status(db, row, "pr_opened", branch=ref, pr_url=url, pr_number=pull.get("number"))
                return
    except Exception:  # a delegation hint must never break the main webhook
        db.rollback()


@router.post("/tasks/{task_id}/delegate", response_model=DelegationRead, status_code=201, dependencies=[Depends(require_token)])
def delegate_task(task_id: str, payload: DelegateRequest | None = None, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    payload = payload or DelegateRequest()
    task = _task_for(db, user, task_id)
    existing = db.scalar(
        select(Delegation).where(Delegation.task_id == task.id, Delegation.status.in_(ACTIVE))
        .order_by(Delegation.created_at.desc())
    )
    if existing is not None:
        return _read(db, existing)
    repo, issue_number = _repo_target(task)
    parts = [task.title.strip(), (task.description or "").strip(), (payload.instruction or "").strip()]
    row = Delegation(
        user_id=user.id, project_id=task.project_id, task_id=task.id, repo=repo, issue_number=issue_number,
        instruction="\n\n".join(p for p in parts if p)[:12000],
        base_branch=(payload.base_branch or "").strip() or None, status="queued",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _read(db, row)


@router.get("/tasks/{task_id}/delegations", response_model=list[DelegationRead], dependencies=[Depends(require_token)])
def list_task_delegations(task_id: str, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    task = _task_for(db, user, task_id)
    rows = db.scalars(
        select(Delegation).where(Delegation.task_id == task.id).order_by(Delegation.created_at.desc(), Delegation.id)
    ).all()
    return [_read(db, r) for r in rows]


@router.get("/delegations", response_model=list[DelegationRead], dependencies=[Depends(require_token)])
def list_delegations(
    status: str = Query(default="queued", max_length=60), repo: str = Query(default="", max_length=600),
    db: Session = Depends(get_db), user: User = Depends(_current_user),
):
    """The caller's OWN delegations, newest first. status may be a comma list; repo is a URL or owner/name."""
    query = select(Delegation).where(Delegation.user_id == user.id)
    wanted = [s.strip() for s in status.split(",") if s.strip()]
    if wanted:
        query = query.where(Delegation.status.in_(wanted))
    rows = list(db.scalars(query.order_by(Delegation.created_at.desc(), Delegation.id)).all())
    if repo.strip():
        key = _repo_key(repo)
        rows = [r for r in rows if r.repo == key]
    return [_read(db, r) for r in rows[:100]]


@router.get("/delegations/{delegation_id}", response_model=DelegationRead, dependencies=[Depends(require_token)])
def get_delegation(delegation_id: str, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    row, _ = _delegation_for(db, user, delegation_id)
    return _read(db, row)


@router.post("/delegations/{delegation_id}/claim", response_model=DelegationRead, dependencies=[Depends(require_token)])
def claim_delegation(delegation_id: str, payload: DelegationClaim | None = None, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    row = _own_delegation(db, user, delegation_id)
    now = now_utc()
    if row.status == "running":
        claimed_at = ws.aware(row.claimed_at)
        if claimed_at is not None and now - claimed_at < STALE_AFTER:
            raise HTTPException(status_code=409, detail="Delegation is already claimed")
    elif row.status != "queued":
        raise HTTPException(status_code=409, detail=f"Delegation is {row.status}")
    row.status = "running"
    row.claimed_by = ((payload.agent if payload else None) or "").strip()[:100] or None
    row.claimed_at = now
    row.started_at = row.started_at or now
    row.updated_at = now
    db.commit()
    db.refresh(row)
    return _read(db, row)


@router.post("/delegations/{delegation_id}/report", response_model=DelegationRead, dependencies=[Depends(require_token)])
def report_delegation(delegation_id: str, payload: DelegationReport, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    row = _own_delegation(db, user, delegation_id)
    claimed_repo = (payload.repo_url or "").strip()
    if claimed_repo and _repo_key(claimed_repo) != row.repo:
        raise HTTPException(
            status_code=409,
            detail=f"Wrong checkout: delegation is for {row.repo}, report came from {claimed_repo}. Run this inside the mapped checkout.",
        )
    if payload.pr_url is not None or payload.status == "pr_opened":
        if not payload.pr_url or not _pr_url_ok(row.repo, payload.pr_url):
            raise HTTPException(status_code=422, detail=f"pr_url must be https://github.com/{row.repo}/pull/<n>")
    apply_status(
        db, row, payload.status, branch=payload.branch, pr_url=payload.pr_url, pr_number=payload.pr_number,
        error=payload.error, summary=payload.summary,
    )
    db.refresh(row)
    return _read(db, row)


@router.post("/delegations/{delegation_id}/cancel", response_model=DelegationRead, dependencies=[Depends(require_token)])
def cancel_delegation(delegation_id: str, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    row, _ = _delegation_for(db, user, delegation_id)
    if row.status in ACTIVE:
        now = now_utc()
        row.status, row.finished_at, row.updated_at = "cancelled", now, now
        db.commit()
        db.refresh(row)
    return _read(db, row)
