"""The hard rule: no figure without a source.

Every monetary figure and section reference in an answer must appear in the retrieved
wording. The prompt asks for this (persuasion); this module enforces it (enforcement).
Deterministic, no model call, and robust to prompt injection it never anticipated, because it
checks the output rather than guessing at the input.

Allowed sources for a figure:
- the retrieved chunks;
- the result of a calculation that code has verified, whose operands come from the chunks
  or the question (DTI-016: "£4,000 + £1,200 - £600 = £4,600");
- the question itself, ONLY as a calculation operand. A figure the user supplied and the
  answer merely repeats ("confirm the excess is £50") is not evidence.

Failure behaviour: a figure mismatch BLOCKS (a wrong number is direct harm); a section
mismatch FLAGS (a wrong reference is an annoyance the handler can see).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from dti_rag.generation import arithmetic
from dti_rag.models import Calculation, RetrievedChunk

MONEY = re.compile(r"£\s?\d[\d,]*(?:\.\d{2})?")
SECTION = re.compile(r"(?:\bSections?\s+|§\s?|\bclauses?\s+)(\d{1,2}(?:\.\d{1,2})?)", re.IGNORECASE)


def normalise_money(text: str) -> str:
    return re.sub(r"[\s,]", "", text).rstrip(".")


def money_in(text: str) -> set[str]:
    return {normalise_money(m.group(0)) for m in MONEY.finditer(text)}


def sections_in(text: str) -> set[str]:
    return {m.group(1) for m in SECTION.finditer(text)}


@dataclass
class FigureCheck:
    unsupported_figures: list[str] = field(default_factory=list)
    unsupported_sections: list[str] = field(default_factory=list)
    unverified_calculations: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.unsupported_figures or self.unverified_calculations:
            return "blocked"
        if self.unsupported_sections:
            return "flagged"
        return "passed"

    def reasons(self) -> list[str]:
        out = [f"figure not in the wording: {f}" for f in self.unsupported_figures]
        out += [f"calculation doesn't add up: {c}" for c in self.unverified_calculations]
        out += [f"section not in the retrieved wording: {s}" for s in self.unsupported_sections]
        return out


def check_figures(
    answer_text: str,
    question: str,
    chunks: list[RetrievedChunk],
    calculations: list[Calculation],
) -> FigureCheck:
    context = "\n".join(c.content for c in chunks)
    in_context = money_in(context)
    in_question = money_in(question)

    computed: set[str] = set()
    result = FigureCheck()
    for calc in calculations:
        operands = {normalise_money(o) for o in arithmetic.operands(calc.expression)}
        sourced = operands <= (in_context | in_question)
        if calc.verified and sourced:
            computed.add(normalise_money(calc.result))
            computed |= operands & in_question  # question figures, used as operands only
        else:
            result.unverified_calculations.append(f"{calc.expression} = {calc.result}")

    allowed = in_context | computed
    result.unsupported_figures = sorted(money_in(answer_text) - allowed)

    known_sections = {c.section_id for c in chunks} | {c.section_group for c in chunks}
    known_sections |= sections_in(context)
    result.unsupported_sections = sorted(sections_in(answer_text) - known_sections)
    return result
