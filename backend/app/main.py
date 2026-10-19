import hmac
import json
import re
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from .config import get_settings
from . import auth as auth_utils
from . import workspaces as ws
from .db import ApiKey, Base, ContextRequest, GitHubRepoLink, ImpactNote, Note, Question, SessionLocal, Task, TechDebt, Update, User, UserSession, engine, get_db, now_utc
from .explain import explain_question
from .github_sync import item_from_webhook, verify_signature
from .mcp_server import create_mcp_server
from .schemas import (
    ContextRequestClaim,
    ContextRequestCreate,
    ContextRequestFulfill,
    ContextRequestRead,
    GitHubLinkRead,
    ImpactNoteCreate,
    ImpactNoteRead,
    NOTE_CATEGORIES,
    NOTE_COLORS,
    NOTE_PRIORITIES,
    NOTE_STATUSES,
    NoteCreate,
    NoteRead,
    NoteUpdate,
    QuestionCreate,
    TASK_PRIORITIES,
    TASK_STATUSES,
    TaskCreate,
    TaskRead,
    TaskReorder,
    TaskUpdate,
    TECH_DEBT_STATUSES,
    TECH_DEBT_URGENCIES,
    TechDebtCreate,
    TechDebtRead,
    TechDebtUpdate,
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
    AccountUpdate,
    AuthResponse,
    LoginRequest,
    QuestionRead,
    RegisterRequest,
    UpdateCreate,
    UpdateRead,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    if settings.database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")) and not settings.updater_token:
        with SessionLocal() as session:
            has_users = session.scalar(select(User.id).limit(1)) is not None
        if not has_users:
            raise RuntimeError(
                "UPDATER_TOKEN is required when using PostgreSQL until a user account is registered"
            )
    _ensure_code_context_columns()
    _ensure_note_columns()
    _ensure_ownership_columns()
    _ensure_project_columns()
    with SessionLocal() as session:
        ws.ensure_default_workspaces(session)
    mcp_app = create_mcp_server().streamable_http_app()
    mcp_mount.app = mcp_app
    try:
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
    finally:
        mcp_mount.app = None


app = FastAPI(title="Updater API", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def _ensure_code_context_columns() -> None:
    from sqlalchemy import inspect, text

    existing = {column["name"] for column in inspect(engine).get_columns("updates")}
    if "code_context" not in existing:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE updates ADD COLUMN code_context JSON"))
    with engine.begin() as connection:
        connection.execute(text("UPDATE updates SET code_context = '[]' WHERE code_context IS NULL"))


def _ensure_ownership_columns() -> None:
    from sqlalchemy import inspect, text

    def columns(table: str) -> set[str]:
        try:
            return {column["name"] for column in inspect(engine).get_columns(table)}
        except Exception:
            return set()

    update_cols = columns("updates")
    ctx_cols = columns("context_requests")
    note_cols = columns("notes")
    task_cols = columns("tasks")
    debt_cols = columns("tech_debt")
    with engine.begin() as connection:
        if "user_id" not in update_cols:
            connection.execute(text("ALTER TABLE updates ADD COLUMN user_id VARCHAR(36)"))
        if "user_id" not in note_cols:
            connection.execute(text("ALTER TABLE notes ADD COLUMN user_id VARCHAR(36)"))
        if "user_id" not in task_cols:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN user_id VARCHAR(36)"))
        if "external_id" not in task_cols:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN external_id VARCHAR(255)"))
        if "external_url" not in task_cols:
            connection.execute(text("ALTER TABLE tasks ADD COLUMN external_url VARCHAR(600)"))
        if "user_id" not in debt_cols:
            connection.execute(text("ALTER TABLE tech_debt ADD COLUMN user_id VARCHAR(36)"))
        if "source_repo_url" not in ctx_cols:
            connection.execute(text("ALTER TABLE context_requests ADD COLUMN source_repo_url VARCHAR(600)"))
        if "source_branch" not in ctx_cols:
            connection.execute(text("ALTER TABLE context_requests ADD COLUMN source_branch VARCHAR(255)"))
        if "source_commit" not in ctx_cols:
            connection.execute(text("ALTER TABLE context_requests ADD COLUMN source_commit VARCHAR(80)"))
        if "claimed_by" not in ctx_cols:
            connection.execute(text("ALTER TABLE context_requests ADD COLUMN claimed_by VARCHAR(100)"))
        if "claimed_at" not in ctx_cols:
            connection.execute(text("ALTER TABLE context_requests ADD COLUMN claimed_at TIMESTAMPTZ"))


def _ensure_project_columns() -> None:
    """Add project_id to the scoped tables and the indexes that depend on it (idempotent).

    Manual DDL left to the operator (no Alembic): databases created before projects keep
    UNIQUE(user_id, repo) on github_repo_links. Drop it by hand if two projects of one
    account need to link the same repo, e.g. on Postgres:
      ALTER TABLE github_repo_links DROP CONSTRAINT github_repo_links_user_id_repo_key;
    SQLite cannot drop a constraint; rebuild the table instead.
    """
    from sqlalchemy import inspect, text

    def columns(table: str) -> set[str]:
        try:
            return {column["name"] for column in inspect(engine).get_columns(table)}
        except Exception:
            return set()

    with engine.begin() as connection:
        for table in ("updates", "tasks", "notes", "tech_debt", "github_repo_links"):
            if "project_id" not in columns(table):
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN project_id VARCHAR(36)"))
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_project_id ON {table} (project_id)"))
    # Unique indexes can fail on dirty legacy data; never block startup for them.
    for statement in (
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_github_repo_links_project_repo ON github_repo_links (project_id, repo)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_project_external ON tasks (project_id, external_id) WHERE external_id IS NOT NULL",
    ):
        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
        except Exception:
            pass


def _optional_user(db, authorization):
    try:
        return _user_for_bearer(db, authorization)
    except Exception:
        return None


def _owner_id(db: Session, authorization: str | None) -> str | None:
    """Id of the signed-in account, or None for the shared env token / open preview."""
    owner = _optional_user(db, authorization)
    return owner.id if owner is not None else None


def require_token(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Accept the legacy env token, a login session, or a per-user API key."""
    if _legacy_token_ok(authorization):
        return None
    if _user_for_bearer(db, authorization) is not None:
        return None
    if _auth_unconfigured(db):
        return None
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token")


def _legacy_token_ok(authorization: str | None) -> bool:
    return bool(settings.updater_token) and hmac.compare_digest(
        authorization or "", "Bearer " + settings.updater_token
    )


def _auth_unconfigured(db: Session) -> bool:
    """True when no env token is set and nobody registered yet (fresh preview)."""
    if settings.updater_token:
        return False
    try:
        return db.scalar(select(User.id).limit(1)) is None
    except Exception:
        return False


def _bearer_value(authorization: str | None) -> str:
    if not authorization:
        return ""
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


def _user_for_bearer(db: Session, authorization: str | None):
    token = _bearer_value(authorization)
    if not token:
        return None
    digest = auth_utils.sha256_hex(token)
    if token.startswith(auth_utils.API_KEY_PREFIX):
        key = db.scalar(
            select(ApiKey).where(ApiKey.key_hash == digest, ApiKey.revoked_at.is_(None))
        )
        if key is None:
            return None
        key.last_used_at = now_utc()
        try:
            db.commit()
        except Exception:
            db.rollback()
        return db.get(User, key.user_id)
    if token.startswith(auth_utils.SESSION_PREFIX):
        session = db.scalar(select(UserSession).where(UserSession.token_hash == digest))
        if session is None:
            return None
        expires = session.expires_at
        now = now_utc()
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=now.tzinfo)
        if expires <= now:
            return None
        return db.get(User, session.user_id)
    return None


_normalize_repo_url = ws.normalize_repo_url


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config", dependencies=[Depends(require_token)])
def config() -> dict[str, bool]:
    return {"ai_enabled": bool(settings.openrouter_api_key)}


@app.get("/api/updates", response_model=list[UpdateRead], dependencies=[Depends(require_token)])
def list_updates(
    response: Response,
    q: str = Query(default="", max_length=200),
    repo: str = Query(default="", max_length=600),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    project_id: str = Query(default="", max_length=80),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[Update]:
    query = select(Update).options(selectinload(Update.questions), selectinload(Update.impact_notes), selectinload(Update.context_requests)).order_by(Update.shipped_at.desc(), Update.created_at.desc(), Update.id.desc())
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(Update.title.ilike(term), Update.summary.ilike(term), Update.why.ilike(term), Update.how_it_works.ilike(term)))
    owner_id = _owner_id(db, authorization)
    query = query.where(ws.project_filter(db, owner_id, Update, project_id.strip()))
    items = list(db.scalars(query).all())
    if repo.strip():
        wanted = _normalize_repo_url(repo)
        items = [u for u in items if _normalize_repo_url(u.repo_url) == wanted]
    total = len(items)
    response.headers["X-Total-Count"] = str(total)
    if offset >= total:
        return []
    return items[offset:offset + limit]


def _merge_republish(existing: Update, payload: UpdateCreate, db: Session) -> Update:
    'Stash a follow-up publish under one feature entry instead of duplicating it.'
    if payload.branch:
        existing.branch = payload.branch
    if payload.commit_sha:
        existing.commit_sha = payload.commit_sha
    if payload.pr_url:
        existing.pr_url = str(payload.pr_url)
    if payload.author_agent:
        existing.author_agent = payload.author_agent
    files = list(existing.files_changed or [])
    for f in payload.files_changed or []:
        if f not in files:
            files.append(f)
    existing.files_changed = files
    tags = list(existing.tags or [])
    for t in payload.tags or []:
        if t not in tags:
            tags.append(t)
    existing.tags = tags
    seen = set()
    for e in existing.code_context or []:
        if isinstance(e, dict):
            seen.add((e.get('path'), e.get('start_line'), e.get('end_line')))
    merged = list(existing.code_context or [])
    for excerpt in payload.code_context or []:
        item = excerpt.model_dump(exclude_none=True)
        key = (item.get('path'), item.get('start_line'), item.get('end_line'))
        if key not in seen:
            merged.append(item)
            seen.add(key)
    existing.code_context = merged[:12]
    db.commit()
    db.refresh(existing)
    return existing


def _find_republish_target(db: Session, payload: UpdateCreate, owner_id: str | None) -> Update | None:
    """Existing entry for this feature key, but only when the caller owns it (or it is unowned)."""
    if not payload.external_id:
        return None
    return db.scalar(
        select(Update)
        .options(selectinload(Update.questions), selectinload(Update.impact_notes), selectinload(Update.context_requests))
        .where(Update.external_id == payload.external_id, ws.project_clause(Update, owner_id))
    )


@app.post("/api/updates", response_model=UpdateRead, status_code=201, dependencies=[Depends(require_token)])
def create_update(payload: UpdateCreate, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Update:
    _ensure_ownership_columns()
    owner_id = _owner_id(db, authorization)
    existing = _find_republish_target(db, payload, owner_id)
    if existing is not None:
        return _merge_republish(existing, payload, db)
    data = payload.model_dump(mode="json", exclude_none=True)
    data["repo_url"] = str(payload.repo_url)
    data["pr_url"] = str(payload.pr_url) if payload.pr_url else None
    data.pop("project_id", None)
    data["project_id"] = ws.resolve_project(db, owner_id, payload.project_id, str(payload.repo_url))
    if owner_id is not None:
        data["user_id"] = owner_id
    if payload.shipped_at:
        data["shipped_at"] = payload.shipped_at
    update = Update(**data)
    db.add(update)
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        existing = _find_republish_target(db, payload, owner_id)
        if existing is not None:
            return _merge_republish(existing, payload, db)
        raise HTTPException(status_code=409, detail="Update already exists") from err
    db.refresh(update)
    return update


def _owned_update(db: Session, update_id: str, owner_id: str | None) -> Update:
    """Fetch an update and reject access when it belongs to a different account."""
    update = db.get(Update, update_id)
    # 404 (not 403) for other accounts so ids cannot be probed.
    if update is None or not ws.row_visible(db, update, owner_id):
        raise HTTPException(status_code=404, detail="Update not found")
    return update


@app.get("/api/updates/{update_id}", response_model=UpdateRead, dependencies=[Depends(require_token)])
def get_update(update_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Update:
    return _owned_update(db, update_id, _owner_id(db, authorization))


@app.post("/api/updates/{update_id}/questions", response_model=QuestionRead, status_code=201, dependencies=[Depends(require_token)])
async def ask_update(update_id: str, payload: QuestionCreate, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Question:
    update = _owned_update(db, update_id, _owner_id(db, authorization))
    answer, source = await explain_question(update, payload.question)
    entry = Question(update_id=update_id, question=payload.question, answer=answer, source=source)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@app.post("/api/updates/{update_id}/impact-notes", response_model=ImpactNoteRead, status_code=201, dependencies=[Depends(require_token)])
def add_impact_note(update_id: str, payload: ImpactNoteCreate, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> ImpactNote:
    _owned_update(db, update_id, _owner_id(db, authorization))
    entry = ImpactNote(update_id=update_id, note=payload.note.strip())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def _normalize_note_color(value: str | None) -> str:
    color = (value or "default").strip().lower()
    if color not in NOTE_COLORS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid color. Choose one of: {', '.join(NOTE_COLORS)}",
        )
    return color


def _normalize_note_category(value: str | None) -> str:
    category = (value or "general").strip().lower()
    if category not in NOTE_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid category. Choose one of: {', '.join(NOTE_CATEGORIES)}",
        )
    return category


def _normalize_note_status(value: str | None) -> str:
    normalized = (value or "open").strip().lower().replace("_", "-")
    if normalized not in NOTE_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status. Choose one of: {', '.join(NOTE_STATUSES)}",
        )
    return normalized


def _normalize_note_priority(value: str | None) -> str:
    priority = (value or "none").strip().lower()
    if priority not in NOTE_PRIORITIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid priority. Choose one of: {', '.join(NOTE_PRIORITIES)}",
        )
    return priority


def _normalize_note_tags(value: list[str] | None) -> list[str]:
    if value is None:
        return []
    cleaned: list[str] = []
    for item in value:
        tag = str(item or "").strip().lower().replace(" ", "-")[:40]
        if tag and tag not in cleaned:
            cleaned.append(tag)
        if len(cleaned) >= 20:
            break
    return cleaned


def _clean_optional_str(value: str | None, max_len: int) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    return text_value[:max_len]


def _ensure_note_columns() -> None:
    from sqlalchemy import inspect, text

    try:
        existing = {column["name"] for column in inspect(engine).get_columns("notes")}
    except Exception:
        return
    # (column_name, ddl_type) pairs — kept generic for SQLite + PostgreSQL.
    wanted: list[tuple[str, str]] = [
        ("category", "VARCHAR(30)"),
        ("status", "VARCHAR(20)"),
        ("priority", "VARCHAR(20)"),
        ("tags", "JSON"),
        ("repository", "VARCHAR(300)"),
        ("branch", "VARCHAR(255)"),
        ("file_path", "VARCHAR(600)"),
        ("commit_hash", "VARCHAR(80)"),
        ("related_url", "VARCHAR(600)"),
        ("due_date", "TIMESTAMPTZ"),
        ("pinned", "BOOLEAN"),
        ("archived", "BOOLEAN"),
    ]
    # Boolean backfill must use TRUE/FALSE (Postgres has no integer-to-boolean cast; 0 aborts startup).
    defaults: dict[str, str] = {
        "category": "'general'",
        "status": "'open'",
        "priority": "'none'",
        "tags": "'[]'",
        "pinned": "FALSE",
        "archived": "FALSE",
    }
    with engine.begin() as connection:
        for name, ddl in wanted:
            if name not in existing:
                connection.execute(text(f"ALTER TABLE notes ADD COLUMN {name} {ddl}"))
        for name, default in defaults.items():
            if name not in existing:
                if name == "tags":
                    connection.execute(text("UPDATE notes SET tags = '[]' WHERE tags IS NULL"))
                else:
                    connection.execute(text(f"UPDATE notes SET {name} = {default} WHERE {name} IS NULL"))


@app.get("/api/notes", response_model=list[NoteRead], dependencies=[Depends(require_token)])
def list_notes(
    project_id: str = Query(default="", max_length=80),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[Note]:
    _ensure_note_columns()
    query = select(Note).order_by(Note.pinned.desc(), Note.updated_at.desc(), Note.created_at.desc())
    query = query.where(ws.project_filter(db, _owner_id(db, authorization), Note, project_id.strip()))
    return list(db.scalars(query).all())


@app.post("/api/notes", response_model=NoteRead, status_code=201, dependencies=[Depends(require_token)])
def create_note(payload: NoteCreate, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Note:
    _ensure_note_columns()
    owner_id = _owner_id(db, authorization)
    entry = Note(
        user_id=owner_id,
        project_id=ws.resolve_project(db, owner_id, payload.project_id, payload.repository),
        title=payload.title.strip(),
        content=(payload.content or "").strip(),
        color=_normalize_note_color(payload.color),
        category=_normalize_note_category(payload.category),
        status=_normalize_note_status(payload.status),
        priority=_normalize_note_priority(payload.priority),
        tags=_normalize_note_tags(payload.tags),
        repository=_clean_optional_str(payload.repository, 300),
        branch=_clean_optional_str(payload.branch, 255),
        file_path=_clean_optional_str(payload.file_path, 600),
        commit_hash=_clean_optional_str(payload.commit_hash, 80),
        related_url=_clean_optional_str(payload.related_url, 600),
        due_date=payload.due_date,
        pinned=bool(payload.pinned),
        archived=bool(payload.archived) or _normalize_note_status(payload.status) == "archived",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@app.patch("/api/notes/{note_id}", response_model=NoteRead, dependencies=[Depends(require_token)])
def update_note(note_id: str, payload: NoteUpdate, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Note:
    _ensure_note_columns()
    owner_id = _owner_id(db, authorization)
    entry = db.get(Note, note_id)
    if not entry or not ws.row_visible(db, entry, owner_id):
        raise HTTPException(status_code=404, detail="Note not found")
    if payload.project_id:
        entry.project_id = ws.find_project(db, owner_id, payload.project_id.strip()).id
    if payload.title is not None:
        entry.title = payload.title.strip()
    if payload.content is not None:
        entry.content = (payload.content or "").strip()
    if payload.color is not None:
        entry.color = _normalize_note_color(payload.color)
    if payload.category is not None:
        entry.category = _normalize_note_category(payload.category)
    if payload.status is not None:
        entry.status = _normalize_note_status(payload.status)
        if entry.status == "archived":
            entry.archived = True
    if payload.priority is not None:
        entry.priority = _normalize_note_priority(payload.priority)
    if payload.tags is not None:
        entry.tags = _normalize_note_tags(payload.tags)
    # Optional string fields: None clears, empty string clears, value sets.
    # NoteUpdate uses None as "not provided" default, so clearing is done
    # by sending an empty string from the client.
    for field_name, max_len in (
        ("repository", 300),
        ("branch", 255),
        ("file_path", 600),
        ("commit_hash", 80),
        ("related_url", 600),
    ):
        value = getattr(payload, field_name)
        # Pydantic keeps the raw value; interpret empty string as clear.
        if value is not None:
            raw = str(value).strip()
            setattr(entry, field_name, raw[:max_len] if raw else None)
    if "due_date" in getattr(payload, "model_fields_set", set()):
        entry.due_date = payload.due_date
    if payload.pinned is not None:
        entry.pinned = bool(payload.pinned)
    if payload.archived is not None:
        entry.archived = bool(payload.archived)
        if not entry.archived and entry.status == "archived":
            entry.status = "open"
    entry.updated_at = now_utc()
    db.commit()
    db.refresh(entry)
    return entry


@app.delete("/api/notes/{note_id}", dependencies=[Depends(require_token)])
def delete_note(note_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    entry = db.get(Note, note_id)
    if not entry or not ws.row_visible(db, entry, _owner_id(db, authorization)):
        raise HTTPException(status_code=404, detail="Note not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}


def _normalize_task_status(value: str | None) -> str:
    normalized = (value or "backlog").strip().lower().replace("_", "-")
    if normalized not in TASK_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status. Choose one of: {', '.join(TASK_STATUSES)}",
        )
    return normalized


def _normalize_task_priority(value: str | None) -> str:
    priority = (value or "medium").strip().lower()
    if priority not in TASK_PRIORITIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid priority. Choose one of: {', '.join(TASK_PRIORITIES)}",
        )
    return priority


def _normalize_task_tags(value: list[str] | None) -> list[str]:
    if value is None:
        return []
    cleaned: list[str] = []
    for item in value:
        tag = str(item or "").strip().lower().replace(" ", "-")[:40]
        if tag and tag not in cleaned:
            cleaned.append(tag)
        if len(cleaned) >= 20:
            break
    return cleaned


def _task_ordering():
    return (Task.status.asc(), Task.position.asc(), Task.created_at.asc(), Task.id.asc())


def _in_project(project_id: str | None):
    return Task.project_id.is_(None) if project_id is None else Task.project_id == project_id


def _column_size(db: Session, status_value: str, project_id: str | None) -> int:
    return int(db.scalar(select(func.count()).select_from(Task).where(Task.status == status_value, _in_project(project_id))) or 0)


def _reindex_task_column(db: Session, status_value: str, project_id: str | None = None) -> None:
    """Compact positions inside one board column of one project after a move or delete."""
    query = select(Task).where(Task.status == status_value, _in_project(project_id))
    items = list(
        db.scalars(
            query.order_by(Task.position.asc(), Task.created_at.asc(), Task.id.asc())
        ).all()
    )
    for index, item in enumerate(items):
        item.position = index


@app.get("/api/tasks", response_model=list[TaskRead], dependencies=[Depends(require_token)])
def list_tasks(
    q: str = Query(default="", max_length=200),
    repo: str = Query(default="", max_length=600),
    status: str = Query(default="", max_length=20),
    priority: str = Query(default="", max_length=20),
    project_id: str = Query(default="", max_length=80),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[Task]:
    query = select(Task).order_by(*_task_ordering())
    query = query.where(ws.project_filter(db, _owner_id(db, authorization), Task, project_id.strip()))
    if status.strip():
        query = query.where(Task.status == _normalize_task_status(status))
    if priority.strip():
        query = query.where(Task.priority == _normalize_task_priority(priority))
    items = list(db.scalars(query).all())
    if repo.strip():
        wanted = _normalize_repo_url(repo)
        items = [t for t in items if t.repo_url and _normalize_repo_url(t.repo_url) == wanted]
    term = q.strip().lower()
    if term:
        items = [
            t
            for t in items
            if term
            in " ".join(
                [
                    t.title or "",
                    t.description or "",
                    t.assignee or "",
                    t.branch or "",
                    " ".join(t.tags or []),
                ]
            ).lower()
        ]
    return items


@app.post("/api/tasks", response_model=TaskRead, status_code=201, dependencies=[Depends(require_token)])
def create_task(payload: TaskCreate, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Task:
    status_value = _normalize_task_status(payload.status)
    owner_id = _owner_id(db, authorization)
    project_id = ws.resolve_project(db, owner_id, payload.project_id, str(payload.repo_url) if payload.repo_url else None)
    next_position = _column_size(db, status_value, project_id)
    entry = Task(
        user_id=owner_id,
        project_id=project_id,
        title=payload.title.strip(),
        description=(payload.description or "").strip(),
        status=status_value,
        priority=_normalize_task_priority(payload.priority),
        position=int(next_position),
        repo_url=str(payload.repo_url) if payload.repo_url else None,
        branch=_clean_optional_str(payload.branch, 255),
        tags=_normalize_task_tags(payload.tags),
        assignee=_clean_optional_str(payload.assignee, 120),
        due_date=payload.due_date,
        author_agent=_clean_optional_str(payload.author_agent, 100),
    )
    if status_value == "done":
        entry.completed_at = now_utc()
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@app.get("/api/tasks/{task_id}", response_model=TaskRead, dependencies=[Depends(require_token)])
def get_task(task_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Task:
    entry = db.get(Task, task_id)
    if not entry or not ws.row_visible(db, entry, _owner_id(db, authorization)):
        raise HTTPException(status_code=404, detail="Task not found")
    return entry


@app.patch("/api/tasks/{task_id}", response_model=TaskRead, dependencies=[Depends(require_token)])
def update_task(task_id: str, payload: TaskUpdate, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Task:
    owner_id = _owner_id(db, authorization)
    entry = db.get(Task, task_id)
    if not entry or not ws.row_visible(db, entry, owner_id):
        raise HTTPException(status_code=404, detail="Task not found")
    old_project_id = entry.project_id
    if payload.project_id:
        target_id = ws.find_project(db, owner_id, payload.project_id.strip()).id
        if target_id != old_project_id:
            position = _column_size(db, entry.status, target_id)
            entry.project_id = target_id
            entry.position = position
            db.flush()
            _reindex_task_column(db, entry.status, old_project_id)
    if payload.title is not None:
        entry.title = payload.title.strip()
    if payload.description is not None:
        entry.description = (payload.description or "").strip()
    if payload.priority is not None:
        entry.priority = _normalize_task_priority(payload.priority)
    if payload.tags is not None:
        entry.tags = _normalize_task_tags(payload.tags)
    for field_name, max_len in (("branch", 255), ("assignee", 120), ("author_agent", 100)):
        value = getattr(payload, field_name)
        if value is not None:
            raw = str(value).strip()
            setattr(entry, field_name, raw[:max_len] if raw else None)
    # Optional URL/date fields use None as "not provided"; use model_fields_set
    # to tell an explicit null (clear) from an omitted field.
    if "repo_url" in payload.model_fields_set:
        entry.repo_url = str(payload.repo_url) if payload.repo_url else None
    if "due_date" in payload.model_fields_set:
        entry.due_date = payload.due_date
    if payload.status is not None:
        status_value = _normalize_task_status(payload.status)
        if status_value != entry.status:
            old_status = entry.status
            position = _column_size(db, status_value, entry.project_id)
            entry.status = status_value
            entry.position = position
            db.flush()
            _reindex_task_column(db, old_status, entry.project_id)
        if status_value == "done":
            entry.completed_at = entry.completed_at or now_utc()
        else:
            entry.completed_at = None
    entry.updated_at = now_utc()
    db.commit()
    db.refresh(entry)
    return entry


def _github_task_status(item) -> str:
    if item.state == "closed":
        return "done"
    return "review" if item.is_pr and not item.draft else "backlog"


def _github_task_scope(owner_id: str | None, project_id: str | None):
    """Tasks of one project; rows with no project fall back to the creator (legacy)."""
    if project_id is not None:
        return Task.project_id == project_id
    return and_(Task.project_id.is_(None), Task.user_id.is_(None) if owner_id is None else Task.user_id == owner_id)


def _upsert_github_task(db: Session, item, owner_id: str | None, repo_url: str, project_id: str | None = None) -> bool:
    """Create or refresh the task for one GitHub item. Returns True when created."""
    kind = "pull-request" if item.is_pr else "issue"
    tags = _normalize_task_tags(["github", kind, *item.labels])
    title = item.title.strip()[:180]
    description = (item.body or "").strip()[:7900]
    remote_done = item.state == "closed"
    entry = db.scalar(select(Task).where(Task.external_id == item.external_id, _github_task_scope(owner_id, project_id)))
    if entry is None:
        status_value = _github_task_status(item)
        position = _column_size(db, status_value, project_id)
        db.add(Task(
            user_id=owner_id, project_id=project_id, title=title, description=description, status=status_value,
            position=int(position), repo_url=repo_url, tags=tags, assignee=item.assignee,
            external_id=item.external_id, external_url=item.url,
            completed_at=now_utc() if remote_done else None,
        ))
        db.flush()
        return True
    entry.title, entry.description, entry.tags = title, description, tags
    entry.assignee, entry.external_url, entry.repo_url = item.assignee, item.url, repo_url
    # Only a change of GitHub state moves the card; local column choices otherwise stay.
    if remote_done and entry.status != "done":
        entry.status, entry.completed_at = "done", now_utc()
    elif not remote_done and entry.status == "done":
        entry.status, entry.completed_at = _github_task_status(item), None
    db.flush()
    return False


@app.get("/api/github/links", response_model=list[GitHubLinkRead], dependencies=[Depends(require_token)])
def list_github_links(
    project_id: str = Query(default="", max_length=80),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[GitHubRepoLink]:
    owner_id = _owner_id(db, authorization)
    query = select(GitHubRepoLink).where(ws.project_filter(db, owner_id, GitHubRepoLink, project_id.strip()))
    return list(db.scalars(query.order_by(GitHubRepoLink.created_at.asc())).all())


@app.delete("/api/github/links/{link_id}", dependencies=[Depends(require_token)])
def delete_github_link(link_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> dict[str, bool]:
    owner_id = _owner_id(db, authorization)
    link = db.get(GitHubRepoLink, link_id)
    if not link or not ws.row_visible(db, link, owner_id):
        raise HTTPException(status_code=404, detail="Link not found")
    db.delete(link)
    db.commit()
    return {"ok": True}


@app.post("/api/github/webhook", include_in_schema=False)
async def github_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, object]:
    """Receive issue and pull request events from a GitHub App or repository webhook."""
    body = await request.body()
    if not settings.github_webhook_secret:
        raise HTTPException(status_code=503, detail="GITHUB_WEBHOOK_SECRET is not configured")
    if not verify_signature(settings.github_webhook_secret, body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=401, detail="Invalid signature")
    event = request.headers.get("x-github-event", "")
    if event == "ping":
        return {"ok": True, "pong": True}
    try:
        payload = json.loads(body)
        if event == "pull_request":
            from .delegation_routes import apply_pr_webhook

            apply_pr_webhook(db, payload)
        parsed = item_from_webhook(event, payload)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="Malformed payload")
    if parsed is None:
        return {"ok": True, "ignored": event}
    repo_name, item = parsed
    links = list(db.scalars(select(GitHubRepoLink).where(GitHubRepoLink.repo == repo_name)).all())
    removed = payload.get("action") in ("deleted", "transferred")
    for link in links:
        if removed:
            for task in db.scalars(select(Task).where(
                Task.external_id == item.external_id,
                _github_task_scope(link.user_id, link.project_id),
            )).all():
                db.delete(task)
        else:
            _upsert_github_task(db, item, link.user_id, f"https://github.com/{repo_name}", link.project_id)
        link.last_event_at = now_utc()
    db.commit()
    for link in links:
        for column in TASK_STATUSES:
            _reindex_task_column(db, column, link.project_id)
    db.commit()
    return {"ok": True, "linked": len(links)}


@app.post("/api/tasks/reorder", response_model=list[TaskRead], dependencies=[Depends(require_token)])
def reorder_tasks(payload: TaskReorder, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> list[Task]:
    """Persist a drag-and-drop board state: ordered task ids per column."""
    if not payload.columns:
        raise HTTPException(status_code=422, detail="Provide at least one column")
    owner_id = _owner_id(db, authorization)
    scope = ws.project_filter(db, owner_id, Task, (payload.project_id or "").strip())
    tasks = {task.id: task for task in db.scalars(select(Task).where(scope)).all()}
    seen: set[str] = set()
    normalized: list[tuple[str, list[str]]] = []
    for raw_status, ids in payload.columns.items():
        status_value = _normalize_task_status(raw_status)
        cleaned: list[str] = []
        for task_id in ids:
            if task_id not in tasks:
                raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
            if task_id in seen:
                raise HTTPException(status_code=422, detail=f"Task listed in more than one column: {task_id}")
            seen.add(task_id)
            cleaned.append(task_id)
        normalized.append((status_value, cleaned))
    now = now_utc()
    for status_value, ids in normalized:
        for index, task_id in enumerate(ids):
            task = tasks[task_id]
            task.status = status_value
            task.position = index
            task.updated_at = now
            if status_value == "done":
                task.completed_at = task.completed_at or now
            else:
                task.completed_at = None
    db.flush()
    touched_projects = {tasks[task_id].project_id for task_id in seen}
    for project_id in touched_projects:
        for status_value in TASK_STATUSES:
            _reindex_task_column(db, status_value, project_id)
    db.commit()
    return list(db.scalars(select(Task).where(scope).order_by(*_task_ordering())).all())


@app.delete("/api/tasks/{task_id}", dependencies=[Depends(require_token)])
def delete_task(task_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    owner_id = _owner_id(db, authorization)
    entry = db.get(Task, task_id)
    if not entry or not ws.row_visible(db, entry, owner_id):
        raise HTTPException(status_code=404, detail="Task not found")
    status_value, project_id = entry.status, entry.project_id
    db.delete(entry)
    db.flush()
    _reindex_task_column(db, status_value, project_id)
    db.commit()
    return {"ok": True}


def _normalize_tech_debt_urgency(value: str | None) -> str:
    urgency = (value or "medium").strip().lower()
    if urgency not in TECH_DEBT_URGENCIES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid urgency. Choose one of: {', '.join(TECH_DEBT_URGENCIES)}",
        )
    return urgency


def _normalize_tech_debt_status(value: str | None) -> str:
    normalized = (value or "open").strip().lower().replace("_", "-")
    if normalized not in TECH_DEBT_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status. Choose one of: {', '.join(TECH_DEBT_STATUSES)}",
        )
    return normalized


@app.get("/api/tech-debt", response_model=list[TechDebtRead], dependencies=[Depends(require_token)])
def list_tech_debt(
    q: str = Query(default="", max_length=200),
    repo: str = Query(default="", max_length=600),
    urgency: str = Query(default="", max_length=20),
    status: str = Query(default="", max_length=20),
    project_id: str = Query(default="", max_length=80),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[TechDebt]:
    query = select(TechDebt).order_by(TechDebt.created_at.desc())
    query = query.where(ws.project_filter(db, _owner_id(db, authorization), TechDebt, project_id.strip()))
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(
            or_(
                TechDebt.title.ilike(term),
                TechDebt.scope.ilike(term),
                TechDebt.description.ilike(term),
                TechDebt.file_path.ilike(term),
            )
        )
    if urgency.strip():
        query = query.where(TechDebt.urgency == urgency.strip().lower())
    if status.strip():
        query = query.where(TechDebt.status == status.strip().lower().replace("_", "-"))
    items = list(db.scalars(query).all())
    if repo.strip():
        wanted = _normalize_repo_url(repo)
        items = [t for t in items if _normalize_repo_url(t.repo_url) == wanted]
    return items


@app.post("/api/tech-debt", response_model=TechDebtRead, status_code=201, dependencies=[Depends(require_token)])
def create_tech_debt(payload: TechDebtCreate, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> TechDebt:
    urgency = _normalize_tech_debt_urgency(payload.urgency)
    status_value = _normalize_tech_debt_status(payload.status)
    owner_id = _owner_id(db, authorization)
    entry = TechDebt(
        user_id=owner_id,
        project_id=ws.resolve_project(db, owner_id, payload.project_id, str(payload.repo_url)),
        title=payload.title.strip(),
        scope=payload.scope.strip(),
        description=payload.description.strip(),
        impact=payload.impact.strip(),
        mitigation=payload.mitigation.strip(),
        current_state=payload.current_state.strip(),
        urgency=urgency,
        status=status_value,
        repo_url=str(payload.repo_url),
        file_path=(payload.file_path or "").strip() or None,
        files=[str(f).strip()[:300] for f in (payload.files or []) if str(f).strip()][:20],
        tags=[str(t).strip().lower().replace(" ", "-")[:40] for t in (payload.tags or []) if str(t).strip()][:20],
        branch=(payload.branch or "").strip() or None,
        commit_sha=(payload.commit_sha or "").strip() or None,
        author_agent=(payload.author_agent or "").strip() or None,
    )
    if status_value in ("resolved", "wont-fix"):
        entry.resolved_at = now_utc()
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@app.get("/api/tech-debt/{debt_id}", response_model=TechDebtRead, dependencies=[Depends(require_token)])
def get_tech_debt(debt_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> TechDebt:
    entry = db.get(TechDebt, debt_id)
    if not entry or not ws.row_visible(db, entry, _owner_id(db, authorization)):
        raise HTTPException(status_code=404, detail="Tech debt item not found")
    return entry


@app.patch("/api/tech-debt/{debt_id}", response_model=TechDebtRead, dependencies=[Depends(require_token)])
def update_tech_debt(debt_id: str, payload: TechDebtUpdate, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> TechDebt:
    owner_id = _owner_id(db, authorization)
    entry = db.get(TechDebt, debt_id)
    if not entry or not ws.row_visible(db, entry, owner_id):
        raise HTTPException(status_code=404, detail="Tech debt item not found")
    if payload.project_id:
        entry.project_id = ws.find_project(db, owner_id, payload.project_id.strip()).id
    if payload.title is not None:
        entry.title = payload.title.strip()
    if payload.scope is not None:
        entry.scope = payload.scope.strip()
    if payload.description is not None:
        entry.description = payload.description.strip()
    if payload.impact is not None:
        entry.impact = payload.impact.strip()
    if payload.mitigation is not None:
        entry.mitigation = payload.mitigation.strip()
    if payload.current_state is not None:
        entry.current_state = payload.current_state.strip()
    if payload.urgency is not None:
        entry.urgency = _normalize_tech_debt_urgency(payload.urgency)
    if payload.status is not None:
        entry.status = _normalize_tech_debt_status(payload.status)
        if entry.status in ("resolved", "wont-fix"):
            entry.resolved_at = entry.resolved_at or now_utc()
        else:
            entry.resolved_at = None
    if payload.file_path is not None:
        raw = (payload.file_path or "").strip()
        entry.file_path = raw or None
    if payload.files is not None:
        entry.files = [str(f).strip()[:300] for f in payload.files if str(f).strip()][:20]
    if payload.tags is not None:
        entry.tags = [str(t).strip().lower().replace(" ", "-")[:40] for t in payload.tags if str(t).strip()][:20]
    if payload.branch is not None:
        raw_branch = (payload.branch or "").strip()
        entry.branch = raw_branch or None
    if payload.commit_sha is not None:
        raw_commit = (payload.commit_sha or "").strip()
        entry.commit_sha = raw_commit or None
    entry.updated_at = now_utc()
    db.commit()
    db.refresh(entry)
    return entry


@app.delete("/api/tech-debt/{debt_id}", dependencies=[Depends(require_token)])
def delete_tech_debt(debt_id: str, db: Session = Depends(get_db), authorization: str | None = Header(default=None)):
    entry = db.get(TechDebt, debt_id)
    if not entry or not ws.row_visible(db, entry, _owner_id(db, authorization)):
        raise HTTPException(status_code=404, detail="Tech debt item not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}


@app.post("/api/updates/{update_id}/context-requests", response_model=ContextRequestRead, status_code=201, dependencies=[Depends(require_token)])
def request_code_context(update_id: str, payload: ContextRequestCreate, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> ContextRequest:
    update = _owned_update(db, update_id, _owner_id(db, authorization))
    update = db.scalar(select(Update).options(selectinload(Update.context_requests)).where(Update.id == update.id))
    pending = [req for req in update.context_requests if req.status == "pending" and req.question.strip() == payload.question.strip()]
    if pending:
        return pending[0]
    entry = ContextRequest(update_id=update_id, question=payload.question.strip())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@app.get("/api/context-requests", response_model=list[ContextRequestRead], dependencies=[Depends(require_token)])
def list_context_requests(status: str = Query(default="pending", max_length=20), repo: str = Query(default="", max_length=600), db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> list[ContextRequest]:
    _ensure_ownership_columns()
    query = select(ContextRequest).join(Update, ContextRequest.update_id == Update.id).options(joinedload(ContextRequest.update)).order_by(ContextRequest.created_at.asc())
    if status.strip():
        wanted_status = status.strip()
        if "," in wanted_status:
            query = query.where(ContextRequest.status.in_([s.strip() for s in wanted_status.split(",") if s.strip()]))
        else:
            query = query.where(ContextRequest.status == wanted_status)
    items = list(db.scalars(query).all())
    owner = _optional_user(db, authorization)
    if owner is not None:
        reachable = set(ws.member_project_ids(db, owner.id) or [])
        items = [
            it for it in items
            if it.update is None
            or (it.update.project_id in reachable if it.update.project_id else it.update.user_id == owner.id)
        ]
    if repo.strip():
        wanted = _normalize_repo_url(repo)
        items = [it for it in items if it.update is not None and _normalize_repo_url(it.update.repo_url) == wanted]
    return items


@app.post("/api/context-requests/{request_id}/fulfill", response_model=ContextRequestRead, dependencies=[Depends(require_token)])
def fulfill_context_request(request_id: str, payload: ContextRequestFulfill, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> ContextRequest:
    _ensure_ownership_columns()
    entry = db.get(ContextRequest, request_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Context request not found")
    if entry.status == "fulfilled":
        return entry
    update = db.get(Update, entry.update_id)
    if update is None:
        raise HTTPException(status_code=404, detail="Update not found")
    owner = _optional_user(db, authorization)
    if owner is not None and not ws.row_visible(db, update, owner.id):
        raise HTTPException(status_code=403, detail="This request belongs to another account")
    claimed_repo = (payload.repo_url or "").strip()
    if claimed_repo:
        if _normalize_repo_url(claimed_repo) != _normalize_repo_url(update.repo_url):
            raise HTTPException(status_code=409, detail=f"Wrong project: request is for {update.repo_url}, fulfill came from {claimed_repo.strip()}. Run this check inside the mapped checkout.")
        entry.source_repo_url = claimed_repo.strip()[:600]
    if payload.branch:
        entry.source_branch = payload.branch.strip()[:255]
    if payload.commit_sha:
        entry.source_commit = payload.commit_sha.strip()[:80]
    excerpts = [excerpt.model_dump(mode="json") for excerpt in payload.excerpts]
    entry.excerpts = excerpts
    entry.status = "fulfilled"
    entry.fulfilled_at = now_utc()
    merged = {str(item.get("path")): dict(item) for item in (update.code_context or []) if isinstance(item, dict)}
    for item in excerpts:
        merged[str(item.get("path"))] = item
    update.code_context = list(merged.values())[:8]
    db.commit()
    db.refresh(entry)
    return entry


@app.post("/api/context-requests/{request_id}/claim", response_model=ContextRequestRead, dependencies=[Depends(require_token)])
def claim_context_request(request_id: str, payload: ContextRequestClaim, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> ContextRequest:
    _ensure_ownership_columns()
    entry = db.get(ContextRequest, request_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Context request not found")
    if entry.status == "fulfilled":
        return entry
    update = db.get(Update, entry.update_id)
    owner = _optional_user(db, authorization)
    if owner is not None and update is not None and not ws.row_visible(db, update, owner.id):
        raise HTTPException(status_code=403, detail="This request belongs to another account")
    agent = (payload.agent or "").strip()[:100] or None
    now = now_utc()
    if entry.status == "claimed" and entry.claimed_at is not None:
        claimed_at = entry.claimed_at
        if claimed_at.tzinfo is None:
            claimed_at = claimed_at.replace(tzinfo=now.tzinfo)
        if (now - claimed_at).total_seconds() < 600:
            return entry
    entry.status = "claimed"
    entry.claimed_at = now
    entry.claimed_by = agent
    db.commit()
    db.refresh(entry)
    return entry


def _current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Return the signed-in user; legacy env tokens cannot act as a user."""
    if _legacy_token_ok(authorization):
        raise HTTPException(status_code=403, detail="Sign in with your account for this action")
    user = _user_for_bearer(db, authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    return user


@app.post("/api/auth/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = auth_utils.normalize_email(payload.email)
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if not settings.allow_open_registration:
        if db.scalar(select(User.id).limit(1)) is not None:
            raise HTTPException(status_code=403, detail="Registration is disabled on this server")
    if db.scalar(select(User).where(User.email == email)) is not None:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(email=email, password_hash=auth_utils.hash_password(payload.password))
    db.add(user)
    try:
        db.flush()
        ws.create_default_workspace(db, user)
        db.commit()
    except IntegrityError as err:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from err
    db.refresh(user)
    token, digest = auth_utils.new_session_token()
    expires_at = auth_utils.session_expiry()
    db.add(UserSession(user_id=user.id, token_hash=digest, expires_at=expires_at))
    db.commit()
    return AuthResponse(email=user.email, session_token=token, expires_at=expires_at)


@app.post("/api/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = auth_utils.normalize_email(payload.email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not auth_utils.verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    token, digest = auth_utils.new_session_token()
    expires_at = auth_utils.session_expiry()
    db.add(UserSession(user_id=user.id, token_hash=digest, expires_at=expires_at))
    db.commit()
    return AuthResponse(email=user.email, session_token=token, expires_at=expires_at)


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    token = _bearer_value(authorization)
    if token.startswith(auth_utils.SESSION_PREFIX):
        session = db.scalar(
            select(UserSession).where(UserSession.token_hash == auth_utils.sha256_hex(token))
        )
        if session is not None:
            db.delete(session)
            db.commit()
    return {"ok": True}


@app.get("/api/auth/me")
def me(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    if _legacy_token_ok(authorization):
        return {"email": None, "legacy": True}
    user = _user_for_bearer(db, authorization)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    return {"email": user.email, "legacy": False}


@app.patch("/api/auth/account")
def update_account(
    payload: AccountUpdate,
    user: User = Depends(_current_user),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Update the signed-in account: email, password, or both.

    The current password is always required. Changing the password revokes every
    other login session; the session used for this request stays signed in.
    """
    if not auth_utils.verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if payload.email is None and not payload.new_password:
        raise HTTPException(status_code=422, detail="Enter a new email or a new password")

    email_changed = False
    if payload.email is not None:
        email = auth_utils.normalize_email(payload.email)
        if "@" not in email or "." not in email.split("@")[-1]:
            raise HTTPException(status_code=422, detail="Enter a valid email address")
        if email != user.email:
            existing = db.scalar(select(User).where(User.email == email, User.id != user.id))
            if existing is not None:
                raise HTTPException(status_code=409, detail="An account with this email already exists")
            user.email = email
            email_changed = True

    password_changed = False
    sessions_revoked = 0
    if payload.new_password:
        if auth_utils.verify_password(payload.new_password, user.password_hash):
            raise HTTPException(status_code=422, detail="New password must be different from the current one")
        user.password_hash = auth_utils.hash_password(payload.new_password)
        password_changed = True
        current = _bearer_value(authorization)
        keep_digest = (
            auth_utils.sha256_hex(current)
            if current.startswith(auth_utils.SESSION_PREFIX)
            else None
        )
        for session in db.scalars(select(UserSession).where(UserSession.user_id == user.id)):
            if keep_digest is not None and session.token_hash == keep_digest:
                continue
            db.delete(session)
            sessions_revoked += 1

    if email_changed or password_changed:
        try:
            db.commit()
        except IntegrityError as err:
            db.rollback()
            raise HTTPException(status_code=409, detail="An account with this email already exists") from err
        db.refresh(user)

    return {
        "email": user.email,
        "email_changed": email_changed,
        "password_changed": password_changed,
        "sessions_revoked": sessions_revoked,
    }


@app.get("/api/auth/keys", response_model=list[ApiKeyRead])
def list_keys(user: User = Depends(_current_user), db: Session = Depends(get_db)):
    return list(
        db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc()))
    )


@app.post("/api/auth/keys", response_model=ApiKeyCreated, status_code=201)
def create_key(payload: ApiKeyCreate, user: User = Depends(_current_user), db: Session = Depends(get_db)):
    key, digest, prefix = auth_utils.new_api_key()
    entry = ApiKey(user_id=user.id, name=payload.name.strip() or "agent key", key_hash=digest, prefix=prefix)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return ApiKeyCreated(id=entry.id, name=entry.name, prefix=entry.prefix, key=key, created_at=entry.created_at)


@app.delete("/api/auth/keys/{key_id}")
def revoke_key(key_id: str, user: User = Depends(_current_user), db: Session = Depends(get_db)):
    entry = db.get(ApiKey, key_id)
    if entry is None or entry.user_id != user.id:
        raise HTTPException(status_code=404, detail="API key not found")
    if entry.revoked_at is None:
        entry.revoked_at = now_utc()
        db.commit()
    return {"ok": True}


def _mcp_authorized(authorization: str) -> bool:
    """Same credential rules as require_token, for the raw MCP transport."""
    if authorization and settings.updater_token and hmac.compare_digest(
        authorization, "Bearer " + settings.updater_token
    ):
        return True
    try:
        with SessionLocal() as db:
            if _auth_unconfigured(db):
                return True
            scheme, _, raw = (authorization or "").partition(" ")
            if scheme.lower() != "bearer":
                return False
            bare = raw.strip()
            if not bare:
                return False
            digest = auth_utils.sha256_hex(bare)
            token = bare
            if token.startswith(auth_utils.API_KEY_PREFIX):
                key = db.scalar(
                    select(ApiKey).where(ApiKey.key_hash == digest, ApiKey.revoked_at.is_(None))
                )
                if key is None:
                    return False
                key.last_used_at = now_utc()
                db.commit()
                return True
            if token.startswith(auth_utils.SESSION_PREFIX):
                session = db.scalar(select(UserSession).where(UserSession.token_hash == digest))
                if session is None:
                    return False
                expires = session.expires_at
                now = now_utc()
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=now.tzinfo)
                return expires > now
    except Exception:
        return False
    return False



class ProtectedMCPApp:
    """Apply the API bearer token to every MCP transport request."""

    def __init__(self) -> None:
        self.app: ASGIApp | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            authorization = next(
                (value.decode("latin-1") for key, value in scope["headers"] if key.lower() == b"authorization"),
                "",
            )
            if not _mcp_authorized(authorization):
                response = JSONResponse({"detail": "Invalid or missing token"}, status_code=401)
                await response(scope, receive, send)
                return
        if self.app is None:
            response = JSONResponse({"detail": "MCP server is starting"}, status_code=503)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


@app.get("/connect.sh", include_in_schema=False)
def connect_script() -> PlainTextResponse:
    # One-step installer: runs mcp add AND installs /updater-* commands.
    script_path = Path(__file__).with_name("connect.sh")
    script = script_path.read_text()
    # Make the bare `curl .../connect.sh | bash` default to this server's
    # public URL, so no --url flag is needed: it prompts for API key,
    # then agent selection. Local dev keeps 127.0.0.1 as default.
    base = (settings.updater_api_url or "").rstrip("/")
    if base and base != "http://127.0.0.1:8000":
        script = script.replace("http://127.0.0.1:8000/mcp", f"{base}/mcp")
    # no-store: a cached or CDN-stale installer is worse than a slow one
    return PlainTextResponse(
        script,
        media_type="text/x-shellscript",
        headers={"Cache-Control": "no-store"},
    )


# Must stay below require_token/_current_user (workspace_routes imports them) and above the "/" mount.
from .workspace_routes import router as workspace_router  # noqa: E402

app.include_router(workspace_router)
from .affinebot_routes import router as affinebot_router  # noqa: E402

app.include_router(affinebot_router)
from .github_routes import router as github_router  # noqa: E402

app.include_router(github_router)
from .delegation_routes import router as delegation_router  # noqa: E402

app.include_router(delegation_router)

mcp_mount = ProtectedMCPApp()
app.mount("/", mcp_mount)
