"""Chunk <-> Search document conversion. Pure; unit-tested offline."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from dti_rag.models import Chunk


def to_offset(d: date) -> str:
    """Edm.DateTimeOffset needs ISO 8601 with an offset. Midnight UTC, by policy (SCHEMA.md)."""
    return f"{d.isoformat()}T00:00:00Z"


def to_search_document(chunk: Chunk, vector: list[float] | None = None) -> dict[str, Any]:
    m = chunk.metadata
    doc: dict[str, Any] = {
        "id": chunk.id,
        "content": chunk.content,
        "doc_id": m.doc_id,
        "edition_year": m.edition_year,
        "version": m.version,
        "status": m.status.value,
        "effective_from": to_offset(m.effective_from),
        "effective_to": to_offset(m.effective_to),
        "supersedes": m.supersedes,
        "superseded_by": m.superseded_by,
        "section_id": m.section_id,
        "section_group": m.section_group,
        "section_title": m.section_title,
        "chunk_kind": m.chunk_kind.value,
        "page": m.page,
        "metadata_json": json.dumps(m.model_dump(mode="json"), sort_keys=True),
    }
    if vector is not None:
        doc["contentVector"] = vector
    return doc


def read_chunks(path: Path) -> list[Chunk]:
    with path.open(encoding="utf-8") as f:
        return [Chunk.model_validate_json(line) for line in f if line.strip()]


def orphan_ids(indexed_ids: set[str], artifact_ids: set[str]) -> set[str]:
    """Documents in the index that the current artefact no longer contains.

    mergeOrUpload never deletes. Without this, a chunk from an old chunking strategy stays
    retrievable for ever.
    """
    return indexed_ids - artifact_ids
