"""Cross-reference following: the top-ranked chunk is sometimes a signpost, not the answer.

    7.2  "...the claim is assessed under Section 3 instead..."      (DTI-018)
    5.1  "...with no fire, is covered under Section 4."              (DTI-019)

The wording is a drafted legal document, so the phrasing is formulaic and a narrow pattern
has high precision. A passing mention ("see Section 9.3") is not a signpost: only phrases
that move the claim to another section are followed.
"""

from __future__ import annotations

import re

from dti_rag.models import RetrievedChunk

SIGNPOST = re.compile(
    r"\b(?:is|are)\s+(?:assessed|covered|dealt with|handled)\s+under\s+Section\s+(\d{1,2})\b",
    re.IGNORECASE,
)


def signposted_sections(chunk: RetrievedChunk) -> set[str]:
    """Top-level sections this chunk hands the claim over to (never its own section)."""
    return {m.group(1) for m in SIGNPOST.finditer(chunk.content)} - {chunk.section_group}


def follow_ups(chunks: list[RetrievedChunk], top_n: int = 5) -> list[tuple[str, str]]:
    """(doc_id, section_group) pairs to retrieve next. Always within the same edition."""
    wanted: list[tuple[str, str]] = []
    retrieved_groups = {(c.doc_id, c.section_group) for c in chunks}
    for chunk in chunks[:top_n]:
        for group in sorted(signposted_sections(chunk)):
            pair = (chunk.doc_id, group)
            if pair not in retrieved_groups and pair not in wanted:
                wanted.append(pair)
    return wanted
