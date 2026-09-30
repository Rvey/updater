from collections.abc import Generator
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Update(Base):
    __tablename__ = "updates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    title: Mapped[str] = mapped_column(String(180))
    summary: Mapped[str] = mapped_column(Text)
    repo_url: Mapped[str] = mapped_column(String(600))
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True)
    commit_sha: Mapped[str | None] = mapped_column(String(80), nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    author_agent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    why: Mapped[str] = mapped_column(Text)
    how_it_works: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(Text)
    tradeoffs: Mapped[str] = mapped_column(Text, default="")
    learning_notes: Mapped[str] = mapped_column(Text, default="")
    files_changed: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    shipped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    questions: Mapped[list["Question"]] = relationship(back_populates="update", cascade="all, delete-orphan", order_by="Question.created_at")
    impact_notes: Mapped[list["ImpactNote"]] = relationship(back_populates="update", cascade="all, delete-orphan", order_by="ImpactNote.created_at")
    code_context: Mapped[list[dict]] = mapped_column(JSON, default=list)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None)
    context_requests: Mapped[list["ContextRequest"]] = relationship(back_populates="update", cascade="all, delete-orphan", order_by="ContextRequest.created_at")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    update_id: Mapped[str] = mapped_column(ForeignKey("updates.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    update: Mapped[Update] = relationship(back_populates="questions")


class ImpactNote(Base):
    __tablename__ = "impact_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    update_id: Mapped[str] = mapped_column(ForeignKey("updates.id", ondelete="CASCADE"))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    update: Mapped[Update] = relationship(back_populates="impact_notes")


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None)
    title: Mapped[str] = mapped_column(String(180), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(20), default="default")
    category: Mapped[str] = mapped_column(String(30), default="general")
    status: Mapped[str] = mapped_column(String(20), default="open")
    priority: Mapped[str] = mapped_column(String(20), default="none")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    repository: Mapped[str | None] = mapped_column(String(300), nullable=True, default=None)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    file_path: Mapped[str | None] = mapped_column(String(600), nullable=True, default=None)
    commit_hash: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    related_url: Mapped[str | None] = mapped_column(String(600), nullable=True, default=None)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    pinned: Mapped[bool] = mapped_column(default=False)
    archived: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="backlog")
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    position: Mapped[int] = mapped_column(default=0)
    repo_url: Mapped[str | None] = mapped_column(String(600), nullable=True, default=None)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    assignee: Mapped[str | None] = mapped_column(String(120), nullable=True, default=None)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    author_agent: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)


class ContextRequest(Base):
    __tablename__ = "context_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    update_id: Mapped[str] = mapped_column(ForeignKey("updates.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    excerpts: Mapped[list[dict]] = mapped_column(JSON, default=list)
    source_repo_url: Mapped[str | None] = mapped_column(String(600), nullable=True, default=None)
    source_branch: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    source_commit: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    claimed_by: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    update: Mapped[Update] = relationship(back_populates="context_requests")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    api_keys: Mapped[list["ApiKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80), default="agent key")
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user: Mapped["User"] = relationship(back_populates="api_keys")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user: Mapped["User"] = relationship(back_populates="sessions")


class TechDebt(Base):
    __tablename__ = "tech_debt"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, default=None)
    title: Mapped[str] = mapped_column(String(180))
    scope: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(Text, default="")
    mitigation: Mapped[str] = mapped_column(Text, default="")
    current_state: Mapped[str] = mapped_column(Text, default="")
    urgency: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="open")
    repo_url: Mapped[str] = mapped_column(String(600), default="")
    file_path: Mapped[str | None] = mapped_column(String(600), nullable=True, default=None)
    files: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    branch: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    commit_sha: Mapped[str | None] = mapped_column(String(80), nullable=True, default=None)
    author_agent: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)


def normalize_database_url(url: str) -> str:
    # Dokploy/env copy-paste often adds surrounding quotes, whitespace, or newlines.
    # Strip them so a valid URL doesn't fail with SQLAlchemy's cryptic
    # "Could not parse SQLAlchemy URL" error.
    cleaned = (url or "").strip().strip("'\"").strip()
    if not cleaned:
        raise RuntimeError(
            "DATABASE_URL is empty. Set it to e.g. "
            "postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require "
            "(URL-encode special chars in the password)."
        )
    if cleaned.startswith("postgres://"):
        return "postgresql+psycopg://" + cleaned[len("postgres://") :]
    if cleaned.startswith("postgresql://"):
        return "postgresql+psycopg://" + cleaned[len("postgresql://") :]
    return cleaned


def _redacted_url(url: str) -> str:
    try:
        from sqlalchemy.engine.url import make_url

        parsed = make_url(normalize_database_url(url))
        # Hide password if present.
        if parsed.password:
            parsed = parsed.set(password="***")
        return str(parsed)
    except Exception:
        # Fall back to showing only scheme + host-ish prefix, never the full secret.
        cleaned = (url or "").strip()
        scheme = cleaned.split("://", 1)[0] if "://" in cleaned else cleaned[:16]
        return f"{scheme}://<redacted> (unparseable, showing scheme only)"


try:
    engine = create_engine(normalize_database_url(get_settings().database_url), pool_pre_ping=True)
except Exception as exc:
    raise RuntimeError(
        "Could not parse DATABASE_URL "
        f"({_redacted_url(get_settings().database_url)}). "
        "Expected format: postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require. "
        "Common fixes: remove surrounding quotes/spaces/newlines, "
        "URL-encode special chars in the password (@ -> %40, / -> %2F, : -> %3A, "
        "# -> %23, ? -> %3F, % -> %25), and make sure the value starts with "
        "postgresql:// or postgres://. "
        f"Underlying error: {exc}"
    ) from exc
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
