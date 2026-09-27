"""Turning Search results into RetrievedChunks."""

from __future__ import annotations

from typing import Any

from dti_rag.models import RetrievedChunk

SELECT_FIELDS = [
    "id",
    "content",
    "doc_id",
    "edition_year",
    "version",
    "effective_from",
    "effective_to",
    "section_id",
    "section_group",
    "section_title",
    "chunk_kind",
    "page",
]


def to_retrieved(result: dict[str, Any]) -> RetrievedChunk:
    return RetrievedChunk(
        **{
            name: result[name]
            for name in SELECT_FIELDS
            if name not in ("effective_from", "effective_to")
        },
        # Search returns DateTimeOffset as an ISO string; the date part is what matters.
        effective_from=str(result["effective_from"])[:10],
        effective_to=str(result["effective_to"])[:10],
        score=result.get("@search.score"),
        reranker_score=result.get("@search.reranker_score"),
    )
