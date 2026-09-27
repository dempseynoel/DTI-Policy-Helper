"""One run of a pipeline over the bank: metadata plus one row per question.

Running the pipeline (slow, costs tokens) is kept separate from scoring the rows (fast,
free), so you can iterate on evaluators without re-generating anything.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class RetrievedRef(BaseModel):
    doc_id: str
    section_id: str
    score: float | None = None


class RunRow(BaseModel):
    qa_id: str
    category: str
    question: str
    pipeline: str  # "baseline" or "current"
    mode: str  # "answer", "ask" or "abstain" (the baseline always "answers")
    answer: str
    retrieved: list[RetrievedRef] = Field(default_factory=list)
    contexts: list[str] = Field(default_factory=list)  # retrieved text, for groundedness
    citations: list[dict[str, Any]] = Field(default_factory=list)
    governing_editions: list[str] = Field(default_factory=list)
    route_reason: str | None = None
    guardrail_status: str | None = None
    trace_id: str | None = None
    latency_ms: int = 0
    error: str | None = None


class RunMeta(BaseModel):
    """Where the numbers came from. Scorecards from different sources aren't comparable."""

    app_env: str
    target: str  # "local" (in-process) or "api" (a deployed endpoint)
    pipeline: str
    prompt_version: str
    git_sha: str
    started_at: str
    temperature: float = 0.0
    serving_models: dict[str, dict[str, Any]] = Field(default_factory=dict)
    index_manifest: dict[str, Any] | None = None
    throttled_responses: int = 0


class Run(BaseModel):
    meta: RunMeta
    rows: list[RunRow]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Run:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
