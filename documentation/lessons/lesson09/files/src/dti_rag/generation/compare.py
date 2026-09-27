"""Cross-edition comparison (DTI-022) and the post-retrieval ambiguity check (DTI-008/009).

Framework-free, so the SDK pipeline and the LangGraph graph (Lesson 09) share it.

"What changed between 2024 and 2025?" is answered by diffing the wording clause by clause,
not by quoting the change summary: 2025's summary omits four real changes. The summary is
passed along as evidence, clearly labelled as possibly incomplete.
"""

from __future__ import annotations

from dataclasses import dataclass

from dti_rag.generation.generate import (
    GeneratedAnswer,
    check_calculations,
    structured_call,
    validate_citations,
)
from dti_rag.generation.prompts import PROMPT_VERSION, SYSTEM_COMPARE, chunk_header
from dti_rag.models import Answer, ChunkKind, RetrievedChunk
from dti_rag.query.router import ASK_NOTE, Mode, Route


@dataclass(frozen=True)
class ClauseChange:
    key: str  # section_id, plus the defined term for Section 1 definitions
    kind: str  # added | removed | changed
    old: RetrievedChunk | None
    new: RetrievedChunk | None


def clause_key(chunk: RetrievedChunk) -> str:
    """Definitions all share section_id '1'; the chunk id's last part tells them apart."""
    if chunk.chunk_kind == ChunkKind.DEFINITION:
        return f"1:{chunk.id.rsplit('__', 1)[-1]}"
    return chunk.section_id


def body(chunk: RetrievedChunk) -> str:
    """The clause text without its edition header, which always differs."""
    return chunk.content.split("\n", 1)[-1].strip()


def diff_editions(old: list[RetrievedChunk], new: list[RetrievedChunk]) -> list[ClauseChange]:
    old_by = {clause_key(c): c for c in old if c.chunk_kind != ChunkKind.DOCUMENT_CONTROL}
    new_by = {clause_key(c): c for c in new if c.chunk_kind != ChunkKind.DOCUMENT_CONTROL}
    changes: list[ClauseChange] = []
    for key in sorted(old_by.keys() | new_by.keys(), key=_sort_key):
        before, after = old_by.get(key), new_by.get(key)
        if before is None:
            changes.append(ClauseChange(key, "added", None, after))
        elif after is None:
            changes.append(ClauseChange(key, "removed", before, None))
        elif body(before) != body(after):
            changes.append(ClauseChange(key, "changed", before, after))
    return changes


def _sort_key(key: str) -> tuple[tuple[int, ...], str]:
    """Document order: '1:flood-re' < '3' < '3.4' < '10'."""
    head = key.split(":")[0]
    return tuple(int(p) if p.isdigit() else 0 for p in head.split(".")), key


def change_summary(chunks: list[RetrievedChunk]) -> RetrievedChunk | None:
    return next((c for c in chunks if c.chunk_kind == ChunkKind.DOCUMENT_CONTROL), None)


def _render(change: ClauseChange) -> str:
    lines = [f"### {change.key} ({change.kind})"]
    if change.old:
        lines += [f"BEFORE {chunk_header(change.old)}", body(change.old)]
    if change.new:
        lines += [f"AFTER {chunk_header(change.new)}", body(change.new)]
    return "\n".join(lines)


def compare(
    question: str, route: Route, chunks_by_edition: dict[str, list[RetrievedChunk]]
) -> Answer:
    editions = sorted(route.editions)
    sections: list[str] = []
    for older, newer in zip(editions, editions[1:], strict=False):
        old_chunks = chunks_by_edition.get(older.doc_id, [])
        new_chunks = chunks_by_edition.get(newer.doc_id, [])
        changes = diff_editions(old_chunks, new_chunks)
        summary = change_summary(new_chunks)
        sections.append(
            f"## {older.label} -> {newer.label}\n"
            f"{len(changes)} clauses differ in the wording.\n\n"
            + "\n\n".join(_render(c) for c in changes)
            + (
                "\n\n### The newer edition's own summary of changes (may be incomplete)\n"
                f"{chunk_header(summary)}\n{body(summary)}"
                if summary
                else ""
            )
        )
    all_chunks = [c for chunks in chunks_by_edition.values() for c in chunks]
    generated: GeneratedAnswer = structured_call(
        SYSTEM_COMPARE, "\n\n".join(sections) + f"\n\n<question>\n{question}\n</question>"
    )
    citations, warnings = validate_citations(generated.citations, all_chunks)
    return Answer(
        mode=route.mode.value,
        text=generated.answer,
        governing_editions=[e.doc_id for e in editions],
        edition_reason=route.reason,
        citations=citations,
        calculations=check_calculations(generated.calculations),
        warnings=warnings,
        prompt_version=PROMPT_VERSION,
    )


def resolve_after_retrieval(
    route: Route, chunks_by_edition: dict[str, list[RetrievedChunk]]
) -> Route:
    """The post-retrieval half of the ambiguity decision deferred in Lesson 07.

    Two editions in scope are only genuinely ambiguous if they disagree. If each edition's
    top-ranked clause is the same clause with identical wording (police notification is 24
    hours in both 2023 editions), answer instead of asking, and say both editions agree.
    """
    if route.mode != Mode.ASK or len(route.editions) < 2:
        return route
    tops = [chunks_by_edition.get(e.doc_id, [])[:1] for e in route.editions]
    if not all(tops):
        return route
    firsts = [t[0] for t in tops]
    same_clause = len({clause_key(c) for c in firsts}) == 1
    same_text = len({body(c) for c in firsts}) == 1
    if not (same_clause and same_text):
        return route
    return Route(
        mode=Mode.ANSWER,
        editions=route.editions,
        reason=route.reason + " Both editions word the relevant clause identically.",
        question_type=route.question_type,
        notes=tuple(n for n in route.notes if n != ASK_NOTE)
        + ("The editions in scope agree on this clause. Say so and give the shared value.",),
        extraction=route.extraction,
    )
