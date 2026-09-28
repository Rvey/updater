from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class CodeExcerpt(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=6000)
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class UpdateCreate(BaseModel):
    external_id: str | None = Field(default=None, max_length=255)
    title: str = Field(min_length=3, max_length=180)
    summary: str = Field(min_length=10)
    repo_url: HttpUrl
    branch: str | None = None
    commit_sha: str | None = None
    pr_url: HttpUrl | None = None
    author_agent: str | None = None
    why: str = Field(min_length=10)
    how_it_works: str = Field(min_length=10)
    impact: str = Field(min_length=10)
    tradeoffs: str = ""
    learning_notes: str = ""
    files_changed: list[str] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=20)
    code_context: list[CodeExcerpt] = Field(default_factory=list, max_length=8)
    shipped_at: datetime | None = None


class QuestionCreate(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class QuestionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    question: str
    answer: str
    source: str
    created_at: datetime


class ImpactNoteCreate(BaseModel):
    note: str = Field(min_length=3, max_length=4000)


class ImpactNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    note: str
    created_at: datetime


NOTE_COLORS = ("default", "red", "orange", "yellow", "green", "blue", "purple", "pink")

NOTE_CATEGORIES = ("todo", "bug", "idea", "investigation", "implementation", "command", "decision", "follow-up", "general")
NOTE_STATUSES = ("open", "in-progress", "done", "archived")
NOTE_PRIORITIES = ("none", "low", "medium", "high")

TECH_DEBT_URGENCIES = ("low", "medium", "high", "critical")
TECH_DEBT_STATUSES = ("open", "in-progress", "resolved", "wont-fix")


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    content: str = Field(default="", max_length=10000)
    color: str = Field(default="default", max_length=20)
    category: str = Field(default="general", max_length=30)
    status: str = Field(default="open", max_length=20)
    priority: str = Field(default="none", max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=20)
    repository: str | None = Field(default=None, max_length=300)
    branch: str | None = Field(default=None, max_length=255)
    file_path: str | None = Field(default=None, max_length=600)
    commit_hash: str | None = Field(default=None, max_length=80)
    related_url: str | None = Field(default=None, max_length=600)
    due_date: datetime | None = None
    pinned: bool = False
    archived: bool = False


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    content: str | None = Field(default=None, max_length=10000)
    color: str | None = Field(default=None, max_length=20)
    category: str | None = Field(default=None, max_length=30)
    status: str | None = Field(default=None, max_length=20)
    priority: str | None = Field(default=None, max_length=20)
    tags: list[str] | None = Field(default=None, max_length=20)
    repository: str | None = Field(default=None, max_length=300)
    branch: str | None = Field(default=None, max_length=255)
    file_path: str | None = Field(default=None, max_length=600)
    commit_hash: str | None = Field(default=None, max_length=80)
    related_url: str | None = Field(default=None, max_length=600)
    due_date: datetime | None = None
    pinned: bool | None = None
    archived: bool | None = None


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    content: str
    color: str
    category: str = "general"
    status: str = "open"
    priority: str = "none"
    tags: list[str] = Field(default_factory=list)
    repository: str | None = None
    branch: str | None = None
    file_path: str | None = None
    commit_hash: str | None = None
    related_url: str | None = None
    due_date: datetime | None = None
    pinned: bool = False
    archived: bool = False
    created_at: datetime
    updated_at: datetime


class ContextRequestCreate(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class ContextRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    update_id: str
    question: str
    status: str
    excerpts: list[CodeExcerpt] = Field(default_factory=list)
    created_at: datetime
    fulfilled_at: datetime | None


class ContextRequestFulfill(BaseModel):
    excerpts: list[CodeExcerpt] = Field(max_length=8)


class TechDebtCreate(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    scope: str = Field(min_length=3, max_length=300)
    description: str = Field(min_length=10)
    impact: str = Field(min_length=10)
    mitigation: str = Field(min_length=10)
    current_state: str = Field(min_length=3, max_length=4000)
    urgency: str = Field(default="medium", max_length=20)
    status: str = Field(default="open", max_length=20)
    repo_url: HttpUrl
    file_path: str | None = Field(default=None, max_length=600)
    files: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=20)
    branch: str | None = None
    commit_sha: str | None = None
    author_agent: str | None = None


class TechDebtUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=180)
    scope: str | None = Field(default=None, min_length=3, max_length=300)
    description: str | None = Field(default=None, min_length=10)
    impact: str | None = Field(default=None, min_length=10)
    mitigation: str | None = Field(default=None, min_length=10)
    current_state: str | None = Field(default=None, min_length=3, max_length=4000)
    urgency: str | None = Field(default=None, max_length=20)
    status: str | None = Field(default=None, max_length=20)
    file_path: str | None = Field(default=None, max_length=600)
    files: list[str] | None = Field(default=None, max_length=20)
    tags: list[str] | None = Field(default=None, max_length=20)
    branch: str | None = None
    commit_sha: str | None = None


class TechDebtRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    scope: str
    description: str
    impact: str
    mitigation: str
    current_state: str
    urgency: str
    status: str
    repo_url: str
    file_path: str | None
    files: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    branch: str | None
    commit_sha: str | None
    author_agent: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class UpdateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_id: str | None
    title: str
    summary: str
    repo_url: str
    branch: str | None
    commit_sha: str | None
    pr_url: str | None
    author_agent: str | None
    why: str
    how_it_works: str
    impact: str
    tradeoffs: str
    learning_notes: str
    files_changed: list[str]
    tags: list[str]
    code_context: list[CodeExcerpt] = Field(default_factory=list)
    shipped_at: datetime
    created_at: datetime
    questions: list[QuestionRead] = Field(default_factory=list)
    impact_notes: list[ImpactNoteRead] = Field(default_factory=list)
    context_requests: list[ContextRequestRead] = Field(default_factory=list)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class AuthResponse(BaseModel):
    email: str
    session_token: str
    expires_at: datetime


class ApiKeyCreate(BaseModel):
    name: str = Field(default="agent key", min_length=1, max_length=80)


class ApiKeyCreated(BaseModel):
    id: str
    name: str
    prefix: str
    key: str
    created_at: datetime


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
