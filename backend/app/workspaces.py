"""Workspaces, projects and membership-based scoping.

Data (tasks, notes, tech debt, updates, GitHub repo links) belongs to a project, and a
project belongs to a workspace. A signed-in account can reach a row when it is a member of
the row's workspace. The shared env token / open preview has no account (``user_id`` None)
and keeps the old unrestricted view.

Authorization failures for non-members are always 404 so ids cannot be probed. A member
who lacks the owner role gets 403.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.orm import Session

from .db import GitHubRepoLink, Note, Project, Task, TechDebt, Update, User, Workspace, WorkspaceMember

INVITE_TTL_DAYS = 7


def normalize_repo_url(value):
    cleaned = (value or "").strip().rstrip("/")
    if cleaned.lower().endswith(".git"):
        cleaned = cleaned[:-4].rstrip("/")
    if cleaned.startswith("git@") and ":" in cleaned:
        host, _, path = cleaned[4:].partition(":")
        cleaned = "https://" + host + "/" + path
    cleaned = re.sub(r"^ssh://(?:git@)?", "https://", cleaned)
    cleaned = re.sub(r"^http://", "https://", cleaned)
    return cleaned.lower()


def slugify(value: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")[:60]
    return slug or fallback


def aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; treat them as UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# --- membership lookups -----------------------------------------------------------------

def get_membership(db: Session, workspace_id: str, user_id: str) -> WorkspaceMember | None:
    return db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id
        )
    )


def member_project_ids(db: Session, user_id: str | None) -> list[str] | None:
    """Ids of every project the account can reach. None means unrestricted (env token)."""
    if user_id is None:
        return None
    return list(
        db.scalars(
            select(Project.id)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Project.workspace_id)
            .where(WorkspaceMember.user_id == user_id)
        ).all()
    )


def project_clause(model, user_id: str | None):
    """SQL filter for rows an account can reach; true() for the env token / open preview.

    A row with no project yet (project_id NULL) stays visible to the account that created
    it, so nothing written between a deploy and the default-project migration disappears.
    """
    if user_id is None:
        return true()
    mine = (
        select(Project.id)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Project.workspace_id)
        .where(WorkspaceMember.user_id == user_id)
    )
    return or_(model.project_id.in_(mine), and_(model.project_id.is_(None), model.user_id == user_id))


def row_visible(db: Session, row, user_id: str | None) -> bool:
    if user_id is None:
        return True
    if row.project_id is None:
        return row.user_id == user_id
    project = db.get(Project, row.project_id)
    return project is not None and get_membership(db, project.workspace_id, user_id) is not None


# --- guards -----------------------------------------------------------------------------

def require_workspace_member(db: Session, user: User, workspace_id: str) -> tuple[Workspace, WorkspaceMember]:
    workspace = db.get(Workspace, workspace_id)
    member = get_membership(db, workspace_id, user.id) if workspace is not None else None
    if workspace is None or member is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace, member


def require_workspace_owner(db: Session, user: User, workspace_id: str) -> tuple[Workspace, WorkspaceMember]:
    workspace, member = require_workspace_member(db, user, workspace_id)
    if member.role != "owner":
        raise HTTPException(status_code=403, detail="Only a workspace owner can do this")
    return workspace, member


def require_project(db: Session, user: User | None, project_id: str) -> Project:
    """Project the account belongs to, else 404. The env token (user None) may open any."""
    project = db.get(Project, project_id)
    if project is None or (user is not None and get_membership(db, project.workspace_id, user.id) is None):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def find_project(db: Session, user_id: str | None, ref: str) -> Project:
    """Resolve a project by id, or by slug among the projects the account can reach."""
    project = db.get(Project, ref)
    if project is not None:
        if user_id is None or get_membership(db, project.workspace_id, user_id) is not None:
            return project
        raise HTTPException(status_code=404, detail="Project not found")
    query = select(Project).where(Project.slug == slugify(ref, ref))
    if user_id is not None:
        query = query.join(WorkspaceMember, WorkspaceMember.workspace_id == Project.workspace_id).where(
            WorkspaceMember.user_id == user_id
        )
    matches = list(db.scalars(query).all())
    if not matches:
        raise HTTPException(status_code=404, detail="Project not found")
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Several projects share this slug; use the project id")
    return matches[0]


def owner_count(db: Session, workspace_id: str) -> int:
    return db.scalar(
        select(func.count()).select_from(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner"
        )
    ) or 0


def ensure_not_last_owner(db: Session, member: WorkspaceMember) -> None:
    if member.role == "owner" and owner_count(db, member.workspace_id) <= 1:
        raise HTTPException(status_code=409, detail="A workspace needs at least one owner")


# --- creation ---------------------------------------------------------------------------

def _unique_workspace_slug(db: Session, name: str) -> str:
    base = slugify(name, "workspace")
    slug = base
    while db.scalar(select(Workspace.id).where(Workspace.slug == slug)) is not None:
        slug = f"{base}-{uuid4().hex[:6]}"
    return slug


def unique_project_slug(db: Session, workspace_id: str, name: str) -> str:
    base = slugify(name, "project")
    slug, n = base, 1
    while db.scalar(select(Project.id).where(Project.workspace_id == workspace_id, Project.slug == slug)) is not None:
        n += 1
        slug = f"{base}-{n}"
    return slug


def create_workspace(db: Session, user: User, name: str) -> Workspace:
    """Workspace with the creator as owner and a default 'General' project. Does not commit."""
    workspace = Workspace(name=name.strip()[:120], slug=_unique_workspace_slug(db, name), created_by=user.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db.add(Project(workspace_id=workspace.id, name="General", slug="general", is_default=True))
    db.flush()
    return workspace


def create_default_workspace(db: Session, user: User) -> Workspace:
    local = (user.email or "user").split("@")[0] or "user"
    return create_workspace(db, user, f"{local} workspace")


def default_project_for(db: Session, user_id: str | None) -> Project | None:
    """The account's default project (earliest membership). Creates a workspace if it has none."""
    if user_id is None:
        return None
    project = db.scalar(
        select(Project)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Project.workspace_id)
        .where(WorkspaceMember.user_id == user_id, Project.is_default.is_(True))
        .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.id.asc())
        .limit(1)
    )
    if project is not None:
        return project
    user = db.get(User, user_id)
    if user is None:
        return None
    workspace = create_default_workspace(db, user)
    db.commit()
    return db.scalar(select(Project).where(Project.workspace_id == workspace.id, Project.is_default.is_(True)))


def resolve_project(db: Session, user_id: str | None, ref: str | None, repo_url: str | None = None) -> str | None:
    """Project id for a write. Explicit ref wins, then a repo_url match, then the default project.

    The env token (user_id None) gets None unless it names a project.
    """
    if ref:
        return find_project(db, user_id, ref.strip()).id
    if user_id is None:
        return None
    wanted = normalize_repo_url(repo_url) if repo_url else ""
    if wanted:
        for project in db.scalars(
            select(Project)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Project.workspace_id)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(Project.is_default.desc(), Project.created_at.asc())
        ).all():
            if project.repo_url and normalize_repo_url(project.repo_url) == wanted:
                return project.id
    default = default_project_for(db, user_id)
    return default.id if default else None


def project_filter(db: Session, user_id: str | None, model, project_ref: str | None):
    """Where-clause for list endpoints: one named project, or the union of reachable ones."""
    if project_ref:
        return model.project_id == find_project(db, user_id, project_ref.strip()).id
    return project_clause(model, user_id)


# --- migration --------------------------------------------------------------------------

def _row_repo(row) -> str:
    if isinstance(row, GitHubRepoLink):
        return f"https://github.com/{row.repo}"
    if isinstance(row, Note):
        return row.repository or ""
    return getattr(row, "repo_url", "") or ""


def ensure_default_workspaces(db: Session) -> None:
    """Idempotent upgrade step: give every account a workspace and put legacy rows in projects.

    1. Each user without a membership gets '<email-local> workspace' + owner membership +
       a default project 'General'.
    2. Rows with project_id NULL and an owner go to that owner's default project, preferring
       a project whose repo_url matches the row's repo.
    3. Rows with no owner at all (written by the env token before accounts) are adopted by
       the first registered account's default project (the v1 decision). They keep user_id
       NULL, so the env token still sees them.
    """
    users = list(db.scalars(select(User).order_by(User.created_at.asc(), User.id.asc())).all())
    if not users:
        return
    for user in users:
        has_membership = db.scalar(select(WorkspaceMember.id).where(WorkspaceMember.user_id == user.id).limit(1))
        if has_membership is None:
            create_default_workspace(db, user)
    db.flush()

    projects_by_user: dict[str, list[Project]] = {}
    for user in users:
        projects_by_user[user.id] = list(
            db.scalars(
                select(Project)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == Project.workspace_id)
                .where(WorkspaceMember.user_id == user.id)
                .order_by(Project.is_default.desc(), Project.created_at.asc())
            ).all()
        )

    def pick(user_id: str, row) -> str | None:
        projects = projects_by_user.get(user_id) or []
        wanted = normalize_repo_url(_row_repo(row))
        if wanted:
            for project in projects:
                if project.repo_url and normalize_repo_url(project.repo_url) == wanted:
                    return project.id
        for project in projects:
            if project.is_default:
                return project.id
        return projects[0].id if projects else None

    first_user = users[0]
    for model in (Update, Note, Task, TechDebt, GitHubRepoLink):
        for row in db.scalars(select(model).where(model.project_id.is_(None))).all():
            owner = row.user_id if row.user_id in projects_by_user else (first_user.id if row.user_id is None else None)
            if owner is None:
                continue
            row.project_id = pick(owner, row)
    db.commit()

