"""Evaluators: one function per metric, each taking a run row and its QA item.

Retrieval, generation and behaviour are scored separately. A correct answer from the wrong
chunk looks like a pass; a blended score hides exactly what you need to fix.

Each evaluator returns True / False, or None when it doesn't apply to that item.
"""

from __future__ import annotations

import re

from evaluation.checks import (
    SHORT_WORD,
    gold_doc_retrieved,
    missing_includes,
    present_excludes,
    section_hit,
)
from evaluation.qa_bank import QAItem
from evaluation.rows import RunRow

DOC_ID = re.compile(r"DTI-HOME-PW-\d{4}-v\d+\.\d+")
MONEY = re.compile(r"£\s?\d[\d,]*")


def weak_includes(item: QAItem) -> list[str]:
    """must_include entries too short to mean much ("not", "one"). Flag, don't trust.

    DTI-007's "not" passes on an answer that says the opposite of what's required.
    """
    return [s for s in item.must_include if s.isalpha() and len(s) <= SHORT_WORD]


def cited_docs(row: RunRow) -> set[str]:
    """Structured citations if the pipeline gives them; doc_ids named in the text otherwise
    (the baseline has no structured citations)."""
    docs = {c["doc_id"] for c in row.citations if "doc_id" in c}
    return docs or set(DOC_ID.findall(row.answer))


# --- retrieval --------------------------------------------------------------------------


def retrieval_recall(row: RunRow, item: QAItem) -> bool | None:
    if not item.answerable:
        return None
    return gold_doc_retrieved([r.doc_id for r in row.retrieved], item.gold_doc_ids)


def retrieval_section_hit(row: RunRow, item: QAItem) -> bool | None:
    if not item.answerable:
        return None
    pairs = [(r.doc_id, r.section_id) for r in row.retrieved]
    return section_hit(pairs, item.gold_doc_ids, item.gold_sections)


def retrieval_purity(row: RunRow, item: QAItem) -> bool | None:
    """Nothing but gold editions in the context. One stray edition is enough to contaminate."""
    if not item.answerable or not row.retrieved:
        return None
    return {r.doc_id for r in row.retrieved} <= set(item.gold_doc_ids)


# --- generation -------------------------------------------------------------------------


def must_include(row: RunRow, item: QAItem) -> bool | None:
    if not item.must_include:
        return None
    return not missing_includes(row.answer, item.must_include)


def must_not_include(row: RunRow, item: QAItem) -> bool | None:
    if not item.must_not_include:
        return None
    return not present_excludes(row.answer, item.must_not_include)


def edition_correct(row: RunRow, item: QAItem) -> bool | None:
    """The domain metric no off-the-shelf evaluator gives you.

    Passes when every gold edition was in scope, at least one gold edition is cited, and
    nothing is cited from outside the editions in scope (no contamination). "£350, per
    Section 3.4" is perfectly grounded in the 2025 chunk; for a 2024 loss it's still wrong,
    and only this catches it.
    """
    if not item.answerable:
        return None
    cited = cited_docs(row)
    governing = set(row.governing_editions) or cited
    gold = set(item.gold_doc_ids)
    return gold <= governing and bool(cited & gold) and cited <= governing


# --- behaviour --------------------------------------------------------------------------


def abstention_correct(row: RunRow, item: QAItem) -> bool | None:
    """For unanswerable items: declined, AND asserted no figure. "I can't confirm, but it was
    probably £250" is a failure."""
    if item.answerable:
        return None
    return row.mode == "abstain" and not MONEY.search(row.answer)


def over_abstained(row: RunRow, item: QAItem) -> bool | None:
    """For answerable items: True is BAD. Abstention is a decision, not a fallback."""
    if not item.answerable:
        return None
    return row.mode == "abstain"


def ambiguity_handled(row: RunRow, item: QAItem) -> bool | None:
    """For ambiguous items: asked, or presented more than one edition. A single value fails
    even when it's the right one."""
    if not item.ambiguous:
        return None
    return row.mode == "ask" or len(cited_docs(row)) >= 2


def no_unsupported_figures(row: RunRow, item: QAItem) -> bool | None:
    """Lesson 11's bar: the figure guardrail never had to block. None before Lesson 11."""
    if row.guardrail_status in (None, "not_checked"):
        return None
    return row.guardrail_status != "blocked"


EVALUATORS = {
    "retrieval_recall": retrieval_recall,
    "retrieval_section_hit": retrieval_section_hit,
    "retrieval_purity": retrieval_purity,
    "must_include": must_include,
    "must_not_include": must_not_include,
    "edition_correct": edition_correct,
    "abstention_correct": abstention_correct,
    "over_abstained": over_abstained,
    "ambiguity_handled": ambiguity_handled,
    "no_unsupported_figures": no_unsupported_figures,
}
