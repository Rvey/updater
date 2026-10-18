"""GitHub repos, issues and PRs through the workspace's Affinebot link (the updater never holds a GitHub token)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import affinebot_client as ab
from . import workspaces as ws
from .affinebot_client import AffinebotClient, AffinebotError
from .db import GitHubRepoLink, Project, Task, User, get_db
from .github_sync import GitHubSyncError, items_from_affinebot, parse_repo
from .main import (
    TASK_STATUSES,
    _current_user,
    _optional_user,
    _reindex_task_column,
    _upsert_github_task,
    require_token,
)
from .schemas import (
    GitHubItemsPage,
    GitHubLinkCreate,
    GitHubLinkCreated,
    GitHubRepoRead,
    GitHubSyncRequest,
    GitHubSyncResult,
)

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

PAGE_SIZE = 100
MAX_PAGES = 10


def _error(exc: AffinebotError) -> HTTPException:
    if exc.status == 404 and exc.detail == "affinebot_not_linked":
        return HTTPException(status_code=409, detail="affinebot_not_linked")
    return ab.http_error_for(exc)


def _client(db: Session, workspace_id: str) -> AffinebotClient:
    try:
        return ab.client_for_workspace(db, workspace_id)
    except AffinebotError as exc:
        raise _error(exc) from None


def _repo_name(value: str) -> str:
    try:
        owner, name = parse_repo(value)
    except GitHubSyncError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return f"{owner}/{name}"


def run_sync(
    db: Session,
    client: AffinebotClient,
    project: Project,
    owner_id: str | None,
    repo: str,
    state: str = "open",
    include_prs: bool = True,
    include_issues: bool = True,
    numbers: list[int] | None = None,
) -> GitHubSyncResult:
    """Fetch every page from Affinebot first, then upsert tasks keyed (external_id, project_id)."""
    kind = "all" if include_prs and include_issues else "pr" if include_prs else "issue" if include_issues else None
    raw: list[dict] = []
    truncated = False
    wanted = set(numbers) if numbers is not None else None
    missing = set(wanted) if wanted is not None else None
    if wanted is not None and not wanted:
        kind = None
    if kind is not None:
        page: int | None = 1
        pages = 0
        while page is not None:
            if pages >= MAX_PAGES:
                truncated = True
                break
            try:
                data = client.items(repo, kind=kind, state=state, page=page, per_page=PAGE_SIZE)
            except AffinebotError as exc:
                raise _error(exc) from None
            rows = data.get("items") or []
            if wanted is not None:
                rows = [row for row in rows if row.get("number") in wanted]
                missing -= {row.get("number") for row in rows}
            raw.extend(rows)
            pages += 1
            if wanted is not None and not missing:
                break
            nxt = data.get("next_page")
            page = nxt if isinstance(nxt, int) and nxt > page else None
    items = items_from_affinebot(repo, raw)
    repo_url = f"https://github.com/{repo}"
    created = updated = 0
    for item in items:
        if _upsert_github_task(db, item, owner_id, repo_url, project.id):
            created += 1
        else:
            updated += 1
    db.commit()
    for column in TASK_STATUSES:
        _reindex_task_column(db, column, project.id)
    db.commit()
    return GitHubSyncResult(repo=repo, created=created, updated=updated, total=len(items), truncated=truncated)


@router.get("/workspaces/{workspace_id}/github/repos", response_model=list[GitHubRepoRead])
def list_repos(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(_current_user)):
    ws.require_workspace_member(db, user, workspace_id)
    client = _client(db, workspace_id)
    try:
        data = client.repos()
    except AffinebotError as exc:
        raise _error(exc) from None
    linked: dict[str, str] = {}
    rows = db.execute(
        select(GitHubRepoLink.repo, GitHubRepoLink.project_id)
        .join(Project, Project.id == GitHubRepoLink.project_id)
        .where(Project.workspace_id == workspace_id)
        .order_by(GitHubRepoLink.created_at.asc())
    ).all()
    for repo, project_id in rows:
        linked.setdefault(repo.lower(), project_id)
    out = []
    for row in data.get("repos") or []:
        name = row.get("full_name") or ""
        project_id = linked.get(name.lower())
        out.append(GitHubRepoRead(
            full_name=name, private=bool(row.get("private")), default_branch=row.get("default_branch"),
            linked=project_id is not None, project_id=project_id,
        ))
    return out


@router.get("/workspaces/{workspace_id}/github/items", response_model=GitHubItemsPage)
def list_items(
    workspace_id: str,
    repo: str = Query(min_length=3, max_length=300),
    kind: str = Query(default="all", pattern="^(issue|pr|all)$"),
    state: str = Query(default="open", pattern="^(open|closed|all)$"),
    page: int = Query(default=1, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(_current_user),
):
    ws.require_workspace_member(db, user, workspace_id)
    name = _repo_name(repo)
    client = _client(db, workspace_id)
    try:
        data = client.items(name, kind=kind, state=state, page=page)
    except AffinebotError as exc:
        raise _error(exc) from None
    rows = [dict(row) for row in data.get("items") or []]  # never mutate the cached payload
    ids = {f"github:{name.lower()}#{row.get('number')}": row for row in rows}
    task_ids: dict[str, str] = {}
    if ids:
        for external_id, task_id in db.execute(
            select(Task.external_id, Task.id)
            .join(Project, Project.id == Task.project_id)
            .where(Task.external_id.in_(list(ids)), Project.workspace_id == workspace_id)
            .order_by(Task.created_at.desc())
        ).all():
            task_ids[external_id] = task_id
    for external_id, row in ids.items():
        row["task_id"] = task_ids.get(external_id)
    return GitHubItemsPage(items=rows, next_page=data.get("next_page"))


@router.post("/github/sync", response_model=GitHubSyncResult)
def sync_github(
    payload: GitHubSyncRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> GitHubSyncResult:
    """Import a repository's issues and PRs as tasks. One-way: GitHub is never written to."""
    user = _optional_user(db, authorization)
    project = ws.require_project(db, user, payload.project_id.strip())
    repo = _repo_name(payload.repo)
    client = _client(db, project.workspace_id)
    return run_sync(
        db, client, project, user.id if user else None, repo,
        state=payload.state, include_prs=payload.include_prs, include_issues=payload.include_issues,
        numbers=payload.numbers,
    )


@router.post("/github/links", response_model=GitHubLinkCreated, status_code=201)
def create_github_link(
    payload: GitHubLinkCreate,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    """Turn on live sync for a repo the Affinebot GitHub App can reach, then run an initial sync."""
    user = _optional_user(db, authorization)
    owner_id = user.id if user else None
    project = ws.require_project(db, user, payload.project_id.strip())
    repo = _repo_name(payload.repo)
    client = _client(db, project.workspace_id)
    try:
        accessible = {(r.get("full_name") or "").lower() for r in client.repos().get("repos") or []}
        if repo.lower() not in accessible:  # the cached list may be stale after the App gained a repo
            accessible = {(r.get("full_name") or "").lower() for r in client.repos(refresh=True).get("repos") or []}
    except AffinebotError as exc:
        raise _error(exc) from None
    if repo.lower() not in accessible:
        raise HTTPException(status_code=404, detail="repo not accessible to the GitHub App")
    name = repo.lower()
    link = db.scalar(select(GitHubRepoLink).where(GitHubRepoLink.repo == name, GitHubRepoLink.project_id == project.id))
    if link is None:
        link = GitHubRepoLink(user_id=owner_id, project_id=project.id, repo=name)
        db.add(link)
        db.commit()
        db.refresh(link)
    result = GitHubLinkCreated.model_validate(link)
    try:
        result.sync = run_sync(db, client, project, owner_id, repo)
    except HTTPException as exc:
        result.sync_error = str(exc.detail)
    return result
