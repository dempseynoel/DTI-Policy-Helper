"""The response contract. The eval harness's API target (Lesson 10) depends on it."""

from __future__ import annotations

from pydantic import BaseModel, Field

from dti_rag.models import Citation


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    answer: str
    mode: str  # answer | ask | abstain: the UI renders each differently
    citations: list[Citation]  # with quoted text, so checking takes seconds
    governing_editions: list[str]
    edition_reason: str  # WHY that edition: the field that makes this an insurance tool
    guardrail_status: str  # passed | flagged | blocked
    guardrail_detail: list[str]
    trace_id: str  # ties the response to the audit log
    prompt_version: str
    git_sha: str


class EditionOut(BaseModel):
    doc_id: str
    edition_year: int
    version: str
    status: str
    effective_from: str
    effective_to: str
