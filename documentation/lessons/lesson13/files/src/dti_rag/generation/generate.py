"""generate(question, route, chunks_by_edition) -> Answer.

Structural fixes, not just prompt rules:

- **One generation pass per edition.** Each pass sees only its own edition's chunks, so a
  2025 aggregation window can't meet a 2024 excess (DTI-015). Contamination is impossible
  rather than discouraged. A final combine pass merges the per-edition answers.
- **Citations are validated.** Every cited (doc_id, section_id) must be a chunk that was
  actually passed in, and the quote must appear in it. Anything else is a fabricated
  citation and is dropped with a warning.
- **Arithmetic is checked in code** (arithmetic.py).
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from dti_rag.clients import openai_client
from dti_rag.config import get_settings
from dti_rag.generation import arithmetic
from dti_rag.generation.prompts import (
    PROMPT_VERSION,
    SYSTEM_ABSTAIN,
    SYSTEM_ANSWER,
    SYSTEM_ASK,
    SYSTEM_COMBINE,
    user_message,
)
from dti_rag.models import Answer, Calculation, Citation, RetrievedChunk
from dti_rag.observability.telemetry import record_usage
from dti_rag.query.router import Mode, Route


class CitedClause(BaseModel):
    doc_id: str
    section_id: str
    quote: str


class WorkedCalculation(BaseModel):
    expression: str
    result: str


class GeneratedAnswer(BaseModel):
    """The structured output every generation call returns."""

    answer: str
    citations: list[CitedClause]
    calculations: list[WorkedCalculation]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def validate_citations(
    cited: list[CitedClause], chunks: list[RetrievedChunk]
) -> tuple[list[Citation], list[str]]:
    by_key = {(c.doc_id, c.section_id): c for c in chunks}
    valid: list[Citation] = []
    warnings: list[str] = []
    for item in cited:
        chunk = by_key.get((item.doc_id, item.section_id))
        if chunk is None:
            warnings.append(f"dropped citation to {item.doc_id} §{item.section_id}: not retrieved")
            continue
        if _squash(item.quote) not in _squash(chunk.content):
            warnings.append(
                f"dropped citation to {item.doc_id} §{item.section_id}: quote not in the clause"
            )
            continue
        citation = Citation(
            doc_id=chunk.doc_id,
            section_id=chunk.section_id,
            section_title=chunk.section_title,
            effective_from=chunk.effective_from,
            effective_to=chunk.effective_to,
            page=chunk.page,
            quoted_text=item.quote,
        )
        if citation not in valid:
            valid.append(citation)
    return valid, warnings


def check_calculations(worked: list[WorkedCalculation]) -> list[Calculation]:
    return [
        Calculation(
            expression=w.expression,
            result=w.result,
            verified=arithmetic.verify(w.expression, w.result),
        )
        for w in worked
    ]


def structured_call(system: str, user: str) -> GeneratedAnswer:
    completion = openai_client().chat.completions.parse(
        model=get_settings().azure_openai_chat_deployment,
        temperature=0,
        response_format=GeneratedAnswer,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    record_usage(completion.usage)
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        refusal = completion.choices[0].message.refusal or "no answer was produced"
        return GeneratedAnswer(
            answer=f"I can't answer that: {refusal}", citations=[], calculations=[]
        )
    return parsed


def text_call(system: str, user: str) -> str:
    completion = openai_client().chat.completions.create(
        model=get_settings().azure_openai_chat_deployment,
        temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    record_usage(completion.usage)
    return completion.choices[0].message.content or ""


def _system_prompt(route: Route, base: str) -> str:
    if route.notes:
        return base + "\n\nFor this question:\n" + "\n".join(f"- {n}" for n in route.notes)
    return base


def _one_pass(question: str, route: Route, system: str, chunks: list[RetrievedChunk]) -> Answer:
    generated = structured_call(
        _system_prompt(route, system), user_message(question, list(route.editions), chunks)
    )
    citations, warnings = validate_citations(generated.citations, chunks)
    return Answer(
        mode=route.mode.value,
        text=generated.answer,
        governing_editions=[e.doc_id for e in route.editions],
        edition_reason=route.reason,
        citations=citations,
        calculations=check_calculations(generated.calculations),
        warnings=warnings,
        prompt_version=PROMPT_VERSION,
    )


def generate(
    question: str, route: Route, chunks_by_edition: dict[str, list[RetrievedChunk]]
) -> Answer:
    all_chunks = [c for chunks in chunks_by_edition.values() for c in chunks]

    if route.mode == Mode.ABSTAIN:
        if not all_chunks:  # nothing to cite (no edition in force): no model call needed
            return Answer(
                mode=route.mode.value,
                text=f"I can't answer this from the policy wording held. {route.reason}",
                governing_editions=[],
                edition_reason=route.reason,
                citations=[],
                prompt_version=PROMPT_VERSION,
            )
        return _one_pass(question, route, SYSTEM_ABSTAIN.format(reason=route.reason), all_chunks)

    if route.mode == Mode.ASK or len(route.editions) == 1:
        # ask mode must present the editions side by side, so it sees them together.
        system = SYSTEM_ASK if route.mode == Mode.ASK else SYSTEM_ANSWER
        return _one_pass(question, route, system, all_chunks)

    # Several editions, no ambiguity: one isolated pass per edition, then combine.
    per_edition: list[tuple[str, Answer]] = []
    for edition in route.editions:
        single = Route(
            mode=Mode.ANSWER,
            editions=(edition,),
            reason=route.reason,
            question_type=route.question_type,
        )
        per_edition.append(
            (
                edition.label,
                _one_pass(
                    question, single, SYSTEM_ANSWER, chunks_by_edition.get(edition.doc_id, [])
                ),
            )
        )
    summaries = "\n\n".join(f"## {label}\n{answer.text}" for label, answer in per_edition)
    combined = text_call(
        _system_prompt(route, SYSTEM_COMBINE),
        f"Edition answers:\n\n{summaries}\n\n<question>\n{question}\n</question>",
    )
    return Answer(
        mode=route.mode.value,
        text=combined,
        governing_editions=[e.doc_id for e in route.editions],
        edition_reason=route.reason,
        citations=[c for _, a in per_edition for c in a.citations],
        calculations=[c for _, a in per_edition for c in a.calculations],
        warnings=[w for _, a in per_edition for w in a.warnings],
        prompt_version=PROMPT_VERSION,
    )
