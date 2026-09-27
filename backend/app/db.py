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


class ContextRequest(Base):
    __tablename__ = "context_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    update_id: Mapped[str] = mapped_column(ForeignKey("updates.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    excerpts: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    update: Mapped[Update] = relationship(back_populates="context_requests")


def normalize_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


engine = create_engine(normalize_database_url(get_settings().database_url), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
