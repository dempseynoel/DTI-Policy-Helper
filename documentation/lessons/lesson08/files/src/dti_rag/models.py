"""Data shapes shared across the pipeline. See documentation/design/SCHEMA.md."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Status(StrEnum):
    """Stored upper case everywhere. OData equality is case-sensitive."""

    ARCHIVED = "ARCHIVED"
    SUPERSEDED = "SUPERSEDED"
    CURRENT = "CURRENT"


class ChunkKind(StrEnum):
    DOCUMENT_CONTROL = "document_control"
    DEFINITION = "definition"
    SECTION_INTRO = "section_intro"
    CLAUSE = "clause"
    EXCESS_SUMMARY = "excess_summary"


class ChunkMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc_id: str
    edition_year: int
    version: str
    status: Status
    effective_from: date
    effective_to: date
    supersedes: str | None
    superseded_by: str | None
    section_id: str
    section_group: str
    section_title: str
    chunk_kind: ChunkKind
    page: int


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    content: str
    metadata: ChunkMetadata


class RetrievedChunk(BaseModel):
    """A chunk as it comes back from Search, with its scores. (Lesson 05)"""

    model_config = ConfigDict(frozen=True)

    id: str
    content: str
    doc_id: str
    edition_year: int
    version: str
    effective_from: date
    effective_to: date
    section_id: str
    section_group: str
    section_title: str
    chunk_kind: ChunkKind
    page: int
    score: float | None = None
    reranker_score: float | None = None


class Citation(BaseModel):
    """Structured, never prose: the evaluators, the guardrails, the UI and the audit log all
    consume it. (Lesson 08)"""

    doc_id: str
    section_id: str
    section_title: str
    effective_from: date
    effective_to: date
    page: int
    quoted_text: str


class Calculation(BaseModel):
    """Arithmetic the model did, shown as working so code can check it. (Lesson 08)"""

    expression: str  # e.g. "£4,000 + £1,200 - £600"
    result: str  # e.g. "£4,600"
    verified: bool = False


class Answer(BaseModel):
    mode: str  # answer | ask | abstain
    text: str
    governing_editions: list[str]
    edition_reason: str
    citations: list[Citation]
    calculations: list[Calculation] = []
    warnings: list[str] = []
    prompt_version: str
