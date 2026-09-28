import hmac
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from .config import get_settings
from . import auth as auth_utils
from .db import ApiKey, Base, ContextRequest, ImpactNote, Note, Question, SessionLocal, TechDebt, Update, User, UserSession, engine, get_db, now_utc
from .explain import explain_question
from .mcp_server import create_mcp_server
from .schemas import (
    ContextRequestClaim,
    ContextRequestCreate,
    ContextRequestFulfill,
    ContextRequestRead,
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
    TECH_DEBT_STATUSES,
    TECH_DEBT_URGENCIES,
    TechDebtCreate,
    TechDebtRead,
    TechDebtUpdate,
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyRead,
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
    try:
        update_cols = {column["name"] for column in inspect(engine).get_columns("updates")}
    except Exception:
        update_cols = set()
    try:
        ctx_cols = {column["name"] for column in inspect(engine).get_columns("context_requests")}
    except Exception:
        ctx_cols = set()
    with engine.begin() as connection:
        if "user_id" not in update_cols:
            connection.execute(text("ALTER TABLE updates ADD COLUMN user_id VARCHAR(36)"))
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


def _optional_user(db, authorization):
    try:
        return _user_for_bearer(db, authorization)
    except Exception:
        return None


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


def _normalize_repo_url(value):
    cleaned = (value or '').strip().rstrip('/')
    if cleaned.lower().endswith('.git'):
        cleaned = cleaned[:-4].rstrip('/')
    if cleaned.startswith('git@') and ':' in cleaned:
        host, _, path = cleaned[4:].partition(':')
        cleaned = 'https://' + host + '/' + path
    return cleaned.lower()


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
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[Update]:
    query = select(Update).options(selectinload(Update.questions), selectinload(Update.impact_notes), selectinload(Update.context_requests)).order_by(Update.shipped_at.desc())
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(Update.title.ilike(term), Update.summary.ilike(term), Update.why.ilike(term), Update.how_it_works.ilike(term)))
    items = list(db.scalars(query).all())
    owner = _optional_user(db, authorization)
    if owner is not None:
        items = [u for u in items if getattr(u, "user_id", None) in (None, owner.id)]
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


@app.post("/api/updates", response_model=UpdateRead, status_code=201, dependencies=[Depends(require_token)])
def create_update(payload: UpdateCreate, db: Session = Depends(get_db), authorization: str | None = Header(default=None)) -> Update:
    _ensure_ownership_columns()
    if payload.external_id:
        existing = db.scalar(select(Update).options(selectinload(Update.questions), selectinload(Update.impact_notes), selectinload(Update.context_requests)).where(Update.external_id == payload.external_id))
        if existing:
            return _merge_republish(existing, payload, db)
    data = payload.model_dump(mode="json", exclude_none=True)
    data["repo_url"] = str(payload.repo_url)
    data["pr_url"] = str(payload.pr_url) if payload.pr_url else None
    owner = _optional_user(db, authorization)
    if owner is not None:
        data["user_id"] = owner.id
    if payload.shipped_at:
        data["shipped_at"] = payload.shipped_at
    update = Update(**data)
    db.add(update)
    try:
        db.commit()
    except IntegrityError as err:
        db.rollback()
        if payload.external_id:
            existing = db.scalar(select(Update).options(selectinload(Update.questions), selectinload(Update.impact_notes), selectinload(Update.context_requests)).where(Update.external_id == payload.external_id))
            if existing:
                return _merge_republish(existing, payload, db)
        raise HTTPException(status_code=409, detail="Update already exists") from err
    db.refresh(update)
    return update


@app.get("/api/updates/{update_id}", response_model=UpdateRead, dependencies=[Depends(require_token)])
def get_update(update_id: str, db: Session = Depends(get_db)) -> Update:
    update = db.scalar(select(Update).options(selectinload(Update.questions), selectinload(Update.impact_notes), selectinload(Update.context_requests)).where(Update.id == update_id))
    if not update:
        raise HTTPException(status_code=404, detail="Update not found")
    return update


@app.post("/api/updates/{update_id}/questions", response_model=QuestionRead, status_code=201, dependencies=[Depends(require_token)])
async def ask_update(update_id: str, payload: QuestionCreate, db: Session = Depends(get_db)) -> Question:
    update = db.get(Update, update_id)
    if not update:
        raise HTTPException(status_code=404, detail="Update not found")
    answer, source = await explain_question(update, payload.question)
    entry = Question(update_id=update_id, question=payload.question, answer=answer, source=source)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@app.post("/api/updates/{update_id}/impact-notes", response_model=ImpactNoteRead, status_code=201, dependencies=[Depends(require_token)])
def add_impact_note(update_id: str, payload: ImpactNoteCreate, db: Session = Depends(get_db)) -> ImpactNote:
    if not db.get(Update, update_id):
        raise HTTPException(status_code=404, detail="Update not found")
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
def list_notes(db: Session = Depends(get_db)) -> list[Note]:
    _ensure_note_columns()
    return list(
        db.scalars(
            select(Note).order_by(Note.pinned.desc(), Note.updated_at.desc(), Note.created_at.desc())
        ).all()
    )


@app.post("/api/notes", response_model=NoteRead, status_code=201, dependencies=[Depends(require_token)])
def create_note(payload: NoteCreate, db: Session = Depends(get_db)) -> Note:
    _ensure_note_columns()
    entry = Note(
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
def update_note(note_id: str, payload: NoteUpdate, db: Session = Depends(get_db)) -> Note:
    _ensure_note_columns()
    entry = db.get(Note, note_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Note not found")
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
def delete_note(note_id: str, db: Session = Depends(get_db)):
    entry = db.get(Note, note_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Note not found")
    db.delete(entry)
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
    db: Session = Depends(get_db),
) -> list[TechDebt]:
    query = select(TechDebt).order_by(TechDebt.created_at.desc())
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
def create_tech_debt(payload: TechDebtCreate, db: Session = Depends(get_db)) -> TechDebt:
    urgency = _normalize_tech_debt_urgency(payload.urgency)
    status_value = _normalize_tech_debt_status(payload.status)
    entry = TechDebt(
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
def get_tech_debt(debt_id: str, db: Session = Depends(get_db)) -> TechDebt:
    entry = db.get(TechDebt, debt_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Tech debt item not found")
    return entry


@app.patch("/api/tech-debt/{debt_id}", response_model=TechDebtRead, dependencies=[Depends(require_token)])
def update_tech_debt(debt_id: str, payload: TechDebtUpdate, db: Session = Depends(get_db)) -> TechDebt:
    entry = db.get(TechDebt, debt_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Tech debt item not found")
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
def delete_tech_debt(debt_id: str, db: Session = Depends(get_db)):
    entry = db.get(TechDebt, debt_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Tech debt item not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}


@app.post("/api/updates/{update_id}/context-requests", response_model=ContextRequestRead, status_code=201, dependencies=[Depends(require_token)])
def request_code_context(update_id: str, payload: ContextRequestCreate, db: Session = Depends(get_db)) -> ContextRequest:
    update = db.scalar(select(Update).options(selectinload(Update.context_requests)).where(Update.id == update_id))
    if not update:
        raise HTTPException(status_code=404, detail="Update not found")
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
        items = [it for it in items if it.update is None or getattr(it.update, "user_id", None) in (None, owner.id)]
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
    if owner is not None and getattr(update, "user_id", None) not in (None, owner.id):
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
    if owner is not None and update is not None and getattr(update, "user_id", None) not in (None, owner.id):
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
    return PlainTextResponse(script, media_type="text/x-shellscript")


mcp_mount = ProtectedMCPApp()
app.mount("/", mcp_mount)
