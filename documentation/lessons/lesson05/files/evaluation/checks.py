"""Cheap, deterministic checks. Lesson 10 builds the full evaluator set on top of these.

Normalisation decides pass/fail, so it is decided once, here:

- Matching is case-insensitive and whitespace-collapsed.
- Figures must match exactly: "£300" does not match "£300.00" or "300 pounds". An insurance
  answer that paraphrases a monetary figure is a worse answer.
- Short alphabetic entries ("not", "one", "two") must match as whole words, so "not" doesn't
  pass on "note" or "cannot". They're still weak tests; Lesson 10 flags them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

SHORT_WORD = 4


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def contains(answer: str, expected: str) -> bool:
    haystack, needle = _normalise(answer), _normalise(expected)
    if needle.isalpha() and len(needle) <= SHORT_WORD:
        return re.search(rf"\b{re.escape(needle)}\b", haystack) is not None
    return needle in haystack


def missing_includes(answer: str, must_include: Iterable[str]) -> list[str]:
    return [item for item in must_include if not contains(answer, item)]


def present_excludes(answer: str, must_not_include: Iterable[str]) -> list[str]:
    return [item for item in must_not_include if contains(answer, item)]


def gold_doc_retrieved(retrieved_doc_ids: Iterable[str], gold_doc_ids: Iterable[str]) -> bool:
    return bool(set(retrieved_doc_ids) & set(gold_doc_ids))


def section_matches(section_id: str, gold_section: str) -> bool:
    """'3.4' matches gold '3.4' and gold '3'. 'Document control' matches only itself."""
    return section_id == gold_section or section_id.startswith(f"{gold_section}.")


def section_hit(
    retrieved: Iterable[tuple[str, str]], gold_doc_ids: Iterable[str], gold_sections: Iterable[str]
) -> bool:
    """A retrieved (doc_id, section_id) pair from a gold document in a gold section.

    Always the pair: section 3.6 in 2022 is a different clause from 3.6 in 2023.
    """
    docs, sections = set(gold_doc_ids), list(gold_sections)
    return any(
        doc in docs and any(section_matches(sec, g) for g in sections) for doc, sec in retrieved
    )
