from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


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
    files_changed: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
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
    shipped_at: datetime
    created_at: datetime
    questions: list[QuestionRead] = Field(default_factory=list)
    impact_notes: list[ImpactNoteRead] = Field(default_factory=list)
