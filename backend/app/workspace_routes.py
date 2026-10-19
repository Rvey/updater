"""Workspace, member, invite and project routes.

Every route needs a real signed-in account (the shared env token gets 403 from
``_current_user``). Non-members get 404, members who are not owners get 403.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import auth as auth_utils
from . import workspaces as ws
from .db import (
    GitHubRepoLink,
    Note,
    Project,
    Task,
    TechDebt,
    Update,
    User,
    Workspace,
    WorkspaceInvite,
    WorkspaceMember,
    get_db,
    now_utc,
)
from .main import _current_user, require_token
from .schemas import (
    InviteAccept,
    InviteAccepted,
    InviteCreate,
    InviteCreated,
    InviteRead,
    MemberAdd,
    MemberAddResult,
    MemberRead,
    MemberRoleUpdate,
    ProjectBrief,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    WorkspaceCreate,
    WorkspaceRead,
    WorkspaceRename,
)

router = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

INVITE_TOKEN_PREFIX = "upi_"


def _workspace_read(db: Session, workspace: Workspace, role: str) -> WorkspaceRead:
    projects = db.scalars(
        select(Project).where(Project.workspace_id == workspace.id).order_by(Project.is_default.desc(), Project.created_at.asc())
    ).all()
    return WorkspaceRead(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        role=role,
        projects=[ProjectBrief.model_validate(p) for p in projects],
    )


def _member_read(member: WorkspaceMember, user: User) -> MemberRead:
    return MemberRead(user_id=user.id, email=user.email, role=member.role, created_at=member.created_at)


def _clean_repo(value: str | None) -> str | None:
    cleaned = ws.normalize_repo_url(value) if value and value.strip() else ""
    return cleaned or None


# --- workspaces -------------------------------------------------------------------------

@router.get("/workspaces", response_model=list[WorkspaceRead])
def list_workspaces(user: User = Depends(_current_user), db: Session = Depends(get_db)) -> list[WorkspaceRead]:
    rows = db.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at.asc(), Workspace.id.asc())
    ).all()
    return [_workspace_read(db, workspace, role) for workspace, role in rows]


@router.post("/workspaces", response_model=WorkspaceRead, status_code=201)
def create_workspace(payload: WorkspaceCreate, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> WorkspaceRead:
    workspace = ws.create_workspace(db, user, payload.name)
    db.commit()
    return _workspace_read(db, workspace, "owner")


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceRead)
def rename_workspace(workspace_id: str, payload: WorkspaceRename, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> WorkspaceRead:
    workspace, member = ws.require_workspace_owner(db, user, workspace_id)
    workspace.name = payload.name.strip()
    db.commit()
    return _workspace_read(db, workspace, member.role)


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> Response:
    workspace, _ = ws.require_workspace_owner(db, user, workspace_id)
    mine = db.scalar(select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.user_id == user.id)) or 0
    if mine <= 1:
        raise HTTPException(status_code=409, detail="You cannot delete your only workspace")
    project_ids = list(db.scalars(select(Project.id).where(Project.workspace_id == workspace.id)).all())
    if project_ids:
        # SQLite does not enforce ON DELETE SET NULL, so remove the data explicitly.
        for model in (Task, Note, TechDebt, Update, GitHubRepoLink):
            for row in db.scalars(select(model).where(model.project_id.in_(project_ids))).all():
                db.delete(row)
    for invite in db.scalars(select(WorkspaceInvite).where(WorkspaceInvite.workspace_id == workspace.id)).all():
        db.delete(invite)
    db.delete(workspace)
    db.commit()
    return Response(status_code=204)


# --- members ----------------------------------------------------------------------------

@router.get("/workspaces/{workspace_id}/members", response_model=list[MemberRead])
def list_members(workspace_id: str, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> list[MemberRead]:
    ws.require_workspace_member(db, user, workspace_id)
    rows = db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.id.asc())
    ).all()
    return [_member_read(member, account) for member, account in rows]


def _new_invite(db: Session, workspace: Workspace, inviter: User, email: str, role: str) -> InviteCreated:
    """Create (or re-issue) the one open invite for this email. Does not commit."""
    for old in db.scalars(
        select(WorkspaceInvite).where(
            WorkspaceInvite.workspace_id == workspace.id,
            WorkspaceInvite.email == email,
            WorkspaceInvite.accepted_at.is_(None),
        )
    ).all():
        db.delete(old)
    db.flush()
    token = INVITE_TOKEN_PREFIX + auth_utils._new_secret()
    invite = WorkspaceInvite(
        workspace_id=workspace.id,
        email=email,
        role=role,
        token_hash=auth_utils.sha256_hex(token),
        invited_by=inviter.id,
        expires_at=now_utc() + timedelta(days=ws.INVITE_TTL_DAYS),
    )
    db.add(invite)
    db.flush()
    return InviteCreated(id=invite.id, email=email, role=role, token=token, expires_at=invite.expires_at)


def _checked_email(raw: str) -> str:
    email = auth_utils.normalize_email(raw)
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return email


@router.post("/workspaces/{workspace_id}/members", response_model=MemberAddResult, status_code=201)
def add_member(workspace_id: str, payload: MemberAdd, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> MemberAddResult:
    workspace, _ = ws.require_workspace_owner(db, user, workspace_id)
    email = _checked_email(payload.email)
    account = db.scalar(select(User).where(User.email == email))
    if account is not None:
        if ws.get_membership(db, workspace.id, account.id) is not None:
            raise HTTPException(status_code=409, detail="Already a member of this workspace")
        member = WorkspaceMember(workspace_id=workspace.id, user_id=account.id, role=payload.role)
        db.add(member)
        db.commit()
        db.refresh(member)
        return MemberAddResult(status="added", member=_member_read(member, account))
    invite = _new_invite(db, workspace, user, email, payload.role)
    db.commit()
    return MemberAddResult(status="invited", invite=invite)


def _member_or_404(db: Session, workspace_id: str, user_id: str) -> WorkspaceMember:
    member = ws.get_membership(db, workspace_id, user_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Member not found")
    return member


@router.patch("/workspaces/{workspace_id}/members/{member_user_id}", response_model=MemberRead)
def change_member_role(workspace_id: str, member_user_id: str, payload: MemberRoleUpdate, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> MemberRead:
    ws.require_workspace_owner(db, user, workspace_id)
    member = _member_or_404(db, workspace_id, member_user_id)
    if member.role == "owner" and payload.role != "owner":
        ws.ensure_not_last_owner(db, member)
    member.role = payload.role
    db.commit()
    return _member_read(member, db.get(User, member.user_id))


@router.delete("/workspaces/{workspace_id}/members/{member_user_id}", status_code=204)
def remove_member(workspace_id: str, member_user_id: str, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> Response:
    _, caller = ws.require_workspace_member(db, user, workspace_id)
    if member_user_id != user.id and caller.role != "owner":
        raise HTTPException(status_code=403, detail="Only a workspace owner can remove other members")
    member = _member_or_404(db, workspace_id, member_user_id)
    ws.ensure_not_last_owner(db, member)
    db.delete(member)
    db.commit()
    return Response(status_code=204)


# --- invites ----------------------------------------------------------------------------

@router.post("/workspaces/{workspace_id}/invites", response_model=InviteCreated, status_code=201)
def create_invite(workspace_id: str, payload: InviteCreate, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> InviteCreated:
    workspace, _ = ws.require_workspace_owner(db, user, workspace_id)
    email = _checked_email(payload.email)
    account = db.scalar(select(User).where(User.email == email))
    if account is not None and ws.get_membership(db, workspace.id, account.id) is not None:
        raise HTTPException(status_code=409, detail="Already a member of this workspace")
    invite = _new_invite(db, workspace, user, email, payload.role)
    db.commit()
    return invite


@router.get("/workspaces/{workspace_id}/invites", response_model=list[InviteRead])
def list_invites(workspace_id: str, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> list[WorkspaceInvite]:
    ws.require_workspace_owner(db, user, workspace_id)
    now = now_utc()
    rows = db.scalars(
        select(WorkspaceInvite)
        .where(WorkspaceInvite.workspace_id == workspace_id, WorkspaceInvite.accepted_at.is_(None))
        .order_by(WorkspaceInvite.created_at.asc())
    ).all()
    return [row for row in rows if ws.aware(row.expires_at) > now]


@router.delete("/workspaces/{workspace_id}/invites/{invite_id}", status_code=204)
def revoke_invite(workspace_id: str, invite_id: str, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> Response:
    ws.require_workspace_owner(db, user, workspace_id)
    invite = db.get(WorkspaceInvite, invite_id)
    if invite is None or invite.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Invite not found")
    db.delete(invite)
    db.commit()
    return Response(status_code=204)


@router.post("/invites/accept", response_model=InviteAccepted)
def accept_invite(payload: InviteAccept, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> InviteAccepted:
    invite = db.scalar(select(WorkspaceInvite).where(WorkspaceInvite.token_hash == auth_utils.sha256_hex(payload.token.strip())))
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=410, detail="This invite was already used")
    if ws.aware(invite.expires_at) <= now_utc():
        raise HTTPException(status_code=410, detail="This invite has expired")
    if auth_utils.normalize_email(user.email) != invite.email:
        raise HTTPException(status_code=403, detail="This invite was sent to a different email address")
    member = ws.get_membership(db, invite.workspace_id, user.id)
    if member is None:
        member = WorkspaceMember(workspace_id=invite.workspace_id, user_id=user.id, role=invite.role)
        db.add(member)
    invite.accepted_at = now_utc()
    db.commit()
    return InviteAccepted(workspace_id=invite.workspace_id, role=member.role)


# --- projects ---------------------------------------------------------------------------

@router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectRead])
def list_projects(workspace_id: str, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> list[Project]:
    ws.require_workspace_member(db, user, workspace_id)
    return list(
        db.scalars(
            select(Project).where(Project.workspace_id == workspace_id).order_by(Project.is_default.desc(), Project.created_at.asc())
        ).all()
    )


@router.post("/workspaces/{workspace_id}/projects", response_model=ProjectRead, status_code=201)
def create_project(workspace_id: str, payload: ProjectCreate, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> Project:
    ws.require_workspace_member(db, user, workspace_id)
    project = Project(
        workspace_id=workspace_id,
        name=payload.name.strip(),
        slug=ws.unique_project_slug(db, workspace_id, payload.name),
        repo_url=_clean_repo(payload.repo_url),
        is_default=False,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.patch("/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: str, payload: ProjectUpdate, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> Project:
    project = ws.require_project(db, user, project_id)
    if payload.name is not None:
        project.name = payload.name.strip()
    if "repo_url" in payload.model_fields_set:
        project.repo_url = _clean_repo(payload.repo_url)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, user: User = Depends(_current_user), db: Session = Depends(get_db)) -> Response:
    project = ws.require_project(db, user, project_id)
    ws.require_workspace_owner(db, user, project.workspace_id)
    if project.is_default:
        raise HTTPException(status_code=409, detail="The default project cannot be deleted")
    for model in (Task, Note, TechDebt, Update):
        if db.scalar(select(model.id).where(model.project_id == project.id).limit(1)) is not None:
            raise HTTPException(status_code=409, detail="Project still has tasks, notes, tech debt or updates")
    for link in db.scalars(select(GitHubRepoLink).where(GitHubRepoLink.project_id == project.id)).all():
        db.delete(link)
    db.delete(project)
    db.commit()
    return Response(status_code=204)
