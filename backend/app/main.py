import hmac
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from . import auth as auth_utils
from .db import ApiKey, Base, ContextRequest, ImpactNote, Question, SessionLocal, Update, User, UserSession, engine, get_db, now_utc
from .explain import explain_question
from .mcp_server import create_mcp_server
from .schemas import (
    ContextRequestCreate,
    ContextRequestFulfill,
    ContextRequestRead,
    ImpactNoteCreate,
    ImpactNoteRead,
    QuestionCreate,
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
    allow_methods=["GET", "POST"],
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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config", dependencies=[Depends(require_token)])
def config() -> dict[str, bool]:
    return {"ai_enabled": bool(settings.openrouter_api_key)}


@app.get("/api/updates", response_model=list[UpdateRead], dependencies=[Depends(require_token)])
def list_updates(
    q: str = Query(default="", max_length=200),
    repo: str = Query(default="", max_length=600),
    db: Session = Depends(get_db),
) -> list[Update]:
    query = select(Update).options(selectinload(Update.questions), selectinload(Update.impact_notes), selectinload(Update.context_requests)).order_by(Update.shipped_at.desc())
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(Update.title.ilike(term), Update.summary.ilike(term), Update.why.ilike(term), Update.how_it_works.ilike(term)))
    if repo.strip():
        query = query.where(Update.repo_url == repo.strip())
    return list(db.scalars(query).all())


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
def create_update(payload: UpdateCreate, db: Session = Depends(get_db)) -> Update:
    if payload.external_id:
        existing = db.scalar(select(Update).options(selectinload(Update.questions), selectinload(Update.impact_notes), selectinload(Update.context_requests)).where(Update.external_id == payload.external_id))
        if existing:
            return _merge_republish(existing, payload, db)
    data = payload.model_dump(mode="json", exclude_none=True)
    data["repo_url"] = str(payload.repo_url)
    data["pr_url"] = str(payload.pr_url) if payload.pr_url else None
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
def list_context_requests(status: str = Query(default="pending", max_length=20), repo: str = Query(default="", max_length=600), db: Session = Depends(get_db)) -> list[ContextRequest]:
    query = select(ContextRequest).join(Update, ContextRequest.update_id == Update.id).order_by(ContextRequest.created_at.asc())
    if status.strip():
        query = query.where(ContextRequest.status == status.strip())
    if repo.strip():
        query = query.where(Update.repo_url == repo.strip())
    return list(db.scalars(query).all())


@app.post("/api/context-requests/{request_id}/fulfill", response_model=ContextRequestRead, dependencies=[Depends(require_token)])
def fulfill_context_request(request_id: str, payload: ContextRequestFulfill, db: Session = Depends(get_db)) -> ContextRequest:
    entry = db.get(ContextRequest, request_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Context request not found")
    if entry.status == "fulfilled":
        return entry
    excerpts = [excerpt.model_dump(mode="json") for excerpt in payload.excerpts]
    entry.excerpts = excerpts
    entry.status = "fulfilled"
    entry.fulfilled_at = now_utc()
    update = db.get(Update, entry.update_id)
    if update is not None:
        merged = {str(item.get("path")): dict(item) for item in (update.code_context or []) if isinstance(item, dict)}
        for item in excerpts:
            merged[str(item.get("path"))] = item
        update.code_context = list(merged.values())[:8]
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
