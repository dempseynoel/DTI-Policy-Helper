"""route(question) -> Route: which editions are in scope, which mode to answer in, and why.

    LLM (fuzzy input)                  Deterministic code (exact, testable)
    "flooded on 15 March 2024"  ──►    date(2024, 3, 15) ──► registry.resolve_by_date ──► Route

The LLM turns language into structure (extract.py). decide() turns structure into a
decision, in pure code, and is unit-tested without a network. This is the edition-selection
policy from SCHEMA.md, executed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from dti_rag.query.editions import (
    Edition,
    EditionRegistry,
    NoEditionInForce,
    is_ambiguous,
    registry,
)
from dti_rag.query.extract import Extraction, extract
from dti_rag.retrieval.filters import DOC_ID, SearchFilter, by_doc

FRESHNESS_NOTE = (
    "No loss date or edition was given, so the current edition applies. State that earlier "
    "editions of the wording may differ, and that the loss date decides which edition governs."
)
ASK_NOTE = (
    "More than one edition could govern. Give the value from each edition with its effective "
    "dates, then ask for the loss date. Never give a single value. If the editions agree, say "
    "so and give the shared value."
)
DOC_ID_IN_TEXT = re.compile(r"DTI-HOME-PW-\d{4}-v\d+\.\d+")


class Mode(StrEnum):
    ANSWER = "answer"
    ASK = "ask"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class Route:
    mode: Mode
    editions: tuple[Edition, ...]
    reason: str  # shown to the handler: why these editions
    question_type: str = "lookup"
    abstain_reason: str | None = None  # out_of_scope | out_of_corpus | no_edition_in_force
    notes: tuple[str, ...] = field(default_factory=tuple)  # instructions for generation
    extraction: Extraction | None = None

    def filters(self) -> list[SearchFilter]:
        """One filter per edition: retrieval runs once per edition, so they never mix."""
        return [by_doc(e.doc_id) for e in self.editions]


def _parse_date(text: str | None) -> date | None:
    """Validate the model's date. An unparseable one is dropped, not guessed at."""
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _abstain(reason_code: str, reason: str, editions: list[Edition], ex: Extraction) -> Route:
    return Route(
        mode=Mode.ABSTAIN,
        editions=tuple(editions),
        reason=reason,
        abstain_reason=reason_code,
        extraction=ex,
    )


def decide(ex: Extraction, reg: EditionRegistry) -> Route:
    current = reg.current()

    # 1. Out of scope: the wording only covers home insurance.
    if ex.scope != "home_policy":
        return _abstain(
            "out_of_scope",
            "The question is not about home insurance; the HomeShield wording can't answer it. "
            "The nearest clauses of the current edition are cited.",
            [current],
            ex,
        )

    # 2. A document named but not held (DTI-024). Deterministic: a set-membership check.
    doc_ids = [d for d in ex.referenced_doc_ids if DOC_ID.match(d)]
    unheld = [d for d in doc_ids if reg.by_doc_id(d) is None]
    if unheld:
        nearest = reg.superseding(unheld[0]) or reg.editions[0]
        return _abstain(
            "out_of_corpus",
            f"{unheld[0]} is not held. Editions held cover {reg.held_range}.",
            [nearest],
            ex,
        )
    unheld_years = [n.year for n in ex.named_editions if not reg.resolve_by_year(n.year)]
    if unheld_years and not doc_ids:
        return _abstain(
            "out_of_corpus",
            f"No {unheld_years[0]} edition is held. Editions held cover {reg.held_range}.",
            [reg.editions[0]],
            ex,
        )

    # 3. A loss date decides, and nothing else does.
    loss_date = _parse_date(ex.loss_date)
    if loss_date is not None:
        try:
            edition = reg.resolve_by_date(loss_date)
        except NoEditionInForce:
            return _abstain(
                "no_edition_in_force",
                f"No held edition was in force on {loss_date:%d %B %Y}. "
                f"Editions held cover {reg.held_range}.",
                [],
                ex,
            )
        return Route(
            mode=Mode.ANSWER,
            editions=(edition,),
            reason=f"The loss date ({loss_date:%d %B %Y}) falls within {edition.label}, "
            f"{edition.in_force}.",
            question_type=ex.question_type,
            extraction=ex,
        )

    # 4. Editions named in the question, by year (and version) or by document reference.
    named: list[Edition] = [e for d in doc_ids if (e := reg.by_doc_id(d))]
    ambiguous_year: int | None = None
    for n in ex.named_editions:
        if n.version and (e := reg.resolve_version(n.year, n.version)):
            named.append(e)
            continue
        in_year = reg.resolve_by_year(n.year)
        if is_ambiguous(in_year):
            ambiguous_year = n.year
        named.extend(in_year)
    named = sorted(set(named))

    if ambiguous_year is not None:
        ranges = "; ".join(
            f"v{e.version} {e.in_force}" for e in reg.resolve_by_year(ambiguous_year)
        )
        return Route(
            mode=Mode.ASK,
            editions=tuple(named),
            reason=f"{ambiguous_year} has more than one edition ({ranges}). The loss date "
            "decides which applies.",
            question_type=ex.question_type,
            notes=(ASK_NOTE,),
            extraction=ex,
        )
    if named:
        labels = ", ".join(e.label for e in named)
        return Route(
            mode=Mode.ANSWER,
            editions=tuple(named),
            reason=f"The question names {labels}.",
            question_type=ex.question_type,
            extraction=ex,
        )

    # 5. "Does X exist / has X changed": every edition, answered per edition.
    if ex.question_type in ("existence_or_history", "comparison"):
        return Route(
            mode=Mode.ANSWER,
            editions=tuple(reg.editions),
            reason="The question asks whether something exists or has changed, so every held "
            f"edition ({reg.held_range}) is checked.",
            question_type=ex.question_type,
            extraction=ex,
        )

    # 6. Nothing temporal: the freshness default, with its caveat.
    return Route(
        mode=Mode.ANSWER,
        editions=(current,),
        reason=f"No loss date or edition was given, so the current edition applies: "
        f"{current.label}, {current.in_force}.",
        question_type=ex.question_type,
        notes=(FRESHNESS_NOTE,),
        extraction=ex,
    )


def route(question: str) -> Route:
    extraction = extract(question)
    # Belt and braces for DTI-024: a document reference in the text is a fact, not a
    # judgement, so it doesn't depend on the model noticing it.
    for doc_id in DOC_ID_IN_TEXT.findall(question):
        if doc_id not in extraction.referenced_doc_ids:
            extraction.referenced_doc_ids.append(doc_id)
    return decide(extraction, registry())
