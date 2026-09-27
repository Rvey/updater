import hmac
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import Base, ImpactNote, Question, Update, engine, get_db
from .explain import explain_question
from .mcp_server import create_mcp_server
from .schemas import ImpactNoteCreate, ImpactNoteRead, QuestionCreate, QuestionRead, UpdateCreate, UpdateRead


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.database_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")) and not settings.updater_token:
        raise RuntimeError("UPDATER_TOKEN is required when using PostgreSQL")
    Base.metadata.create_all(bind=engine)
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


def require_token(authorization: str | None = Header(default=None)) -> None:
    if settings.updater_token and not hmac.compare_digest(authorization or "", f"Bearer {settings.updater_token}"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing token")


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
    query = select(Update).options(selectinload(Update.questions), selectinload(Update.impact_notes)).order_by(Update.shipped_at.desc())
    if q.strip():
        term = f"%{q.strip()}%"
        query = query.where(or_(Update.title.ilike(term), Update.summary.ilike(term), Update.why.ilike(term), Update.how_it_works.ilike(term)))
    if repo.strip():
        query = query.where(Update.repo_url == repo.strip())
    return list(db.scalars(query).all())


@app.post("/api/updates", response_model=UpdateRead, status_code=201, dependencies=[Depends(require_token)])
def create_update(payload: UpdateCreate, db: Session = Depends(get_db)) -> Update:
    if payload.external_id:
        existing = db.scalar(select(Update).options(selectinload(Update.questions), selectinload(Update.impact_notes)).where(Update.external_id == payload.external_id))
        if existing:
            return existing
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
            existing = db.scalar(select(Update).options(selectinload(Update.questions), selectinload(Update.impact_notes)).where(Update.external_id == payload.external_id))
            if existing:
                return existing
        raise HTTPException(status_code=409, detail="Update already exists") from err
    db.refresh(update)
    return update


@app.get("/api/updates/{update_id}", response_model=UpdateRead, dependencies=[Depends(require_token)])
def get_update(update_id: str, db: Session = Depends(get_db)) -> Update:
    update = db.scalar(select(Update).options(selectinload(Update.questions), selectinload(Update.impact_notes)).where(Update.id == update_id))
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
            if settings.updater_token and not hmac.compare_digest(authorization, f"Bearer {settings.updater_token}"):
                response = JSONResponse({"detail": "Invalid or missing token"}, status_code=401)
                await response(scope, receive, send)
                return
        if self.app is None:
            response = JSONResponse({"detail": "MCP server is starting"}, status_code=503)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


mcp_mount = ProtectedMCPApp()
app.mount("/", mcp_mount)
