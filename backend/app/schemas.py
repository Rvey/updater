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
