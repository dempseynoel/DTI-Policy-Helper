from datetime import date

import pytest

from dti_rag.generation import arithmetic, generate
from dti_rag.generation.crossref import follow_ups, signposted_sections
from dti_rag.generation.generate import (
    CitedClause,
    GeneratedAnswer,
    WorkedCalculation,
    validate_citations,
)
from dti_rag.generation.prompts import SYSTEM_ABSTAIN, format_context
from dti_rag.models import ChunkKind, RetrievedChunk
from dti_rag.query.editions import load_registry
from dti_rag.query.router import Mode, Route

REG = load_registry()


def chunk(doc_id: str, section_id: str, content: str) -> RetrievedChunk:
    edition = REG.by_doc_id(doc_id)
    return RetrievedChunk(
        id=f"{doc_id}__{section_id}".replace(".", "_"),
        content=content,
        doc_id=doc_id,
        edition_year=edition.edition_year,
        version=edition.version,
        effective_from=edition.effective_from,
        effective_to=edition.effective_to,
        section_id=section_id,
        section_group=section_id.split(".")[0],
        section_title="t",
        chunk_kind=ChunkKind.CLAUSE,
        page=5,
    )


E2024, E2025 = "DTI-HOME-PW-2024-v1.0", "DTI-HOME-PW-2025-v1.0"


# --- arithmetic -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression, result",
    [
        ("£4,000 + £1,200 - £600", "£4,600"),  # DTI-016
        ("2 × £300", "£600"),  # DTI-015, 2024
        ("2 x £300", "£600"),
        ("(£4,000 + £1,200) - £600", "£4,600"),
    ],
)
def test_correct_arithmetic_verifies(expression, result):
    assert arithmetic.verify(expression, result)


@pytest.mark.parametrize(
    "expression, result",
    [
        ("£4,000 + £1,200 - £350", "£4,600"),  # the characteristic DTI-016 mistake
        ("__import__('os').system('true')", "£0"),
        ("", "£1"),
    ],
)
def test_wrong_or_unsafe_arithmetic_fails(expression, result):
    assert not arithmetic.verify(expression, result)


def test_operands_are_the_figures_used():
    assert arithmetic.operands("£4,000 + £1,200 - £600") == ["£4,000", "£1,200", "£600"]


# --- cross-references ---------------------------------------------------------------------


def test_signpost_in_7_2_points_to_section_3():
    c = chunk(
        E2025,
        "7.2",
        "Where a ceiling collapse was caused by escaping water, "
        "the claim is assessed under Section 3 instead.",
    )
    assert signposted_sections(c) == {"3"}
    assert follow_ups([c]) == [(E2025, "3")]


def test_signpost_in_5_1_points_to_section_4():
    c = chunk(
        E2024,
        "5.1",
        "A lightning strike causing only a power surge, with no fire, is covered under Section 4.",
    )
    assert signposted_sections(c) == {"4"}


def test_a_passing_mention_is_not_a_signpost():
    c = chunk(
        E2025,
        "2",
        "we may cancel your policy from the date of the fraudulent act. See Section 9.3.",
    )
    assert signposted_sections(c) == set()


def test_no_follow_up_when_the_section_was_already_retrieved():
    signpost = chunk(E2025, "7.2", "the claim is assessed under Section 3 instead")
    already = chunk(E2025, "3.4", "The standard excess ... is £350.")
    assert follow_ups([signpost, already]) == []


# --- citations ----------------------------------------------------------------------------


def test_citations_must_point_at_retrieved_chunks_and_quote_them():
    chunks = [chunk(E2024, "3.4", "The standard excess for an escape of water claim is £300.")]
    cited = [
        CitedClause(
            doc_id=E2024,
            section_id="3.4",
            quote="standard excess for an escape of water claim is £300",
        ),
        CitedClause(doc_id=E2025, section_id="3.4", quote="£350"),  # not retrieved
        CitedClause(doc_id=E2024, section_id="3.4", quote="the excess is £250"),  # not in the text
    ]
    valid, warnings = validate_citations(cited, chunks)
    assert [(c.doc_id, c.section_id) for c in valid] == [(E2024, "3.4")]
    assert valid[0].effective_from == date(2024, 1, 1)
    assert len(warnings) == 2


def test_context_headers_carry_edition_and_section():
    text = format_context([chunk(E2024, "3.4", "£300")])
    assert f"doc_id={E2024}" in text and "section_id=3.4" in text and "01 Jan 2024" in text


def test_abstain_prompt_takes_the_reason():
    assert "2021 is not held" in SYSTEM_ABSTAIN.format(reason="2021 is not held")


# --- per-edition isolation ----------------------------------------------------------------


def test_each_edition_is_generated_from_its_own_chunks_only(monkeypatch):
    seen: list[str] = []

    def fake_structured(system, user):
        seen.append(user)
        doc = E2024 if E2024 in user.split("Extracts:")[1] else E2025
        return GeneratedAnswer(
            answer=f"answer for {doc}",
            citations=[CitedClause(doc_id=doc, section_id="4.5", quote="window")],
            calculations=[WorkedCalculation(expression="2 × £300", result="£600")],
        )

    monkeypatch.setattr(generate, "structured_call", fake_structured)
    monkeypatch.setattr(generate, "text_call", lambda system, user: "combined")

    route = Route(
        mode=Mode.ANSWER, editions=(REG.by_doc_id(E2024), REG.by_doc_id(E2025)), reason="named"
    )
    chunks = {
        E2024: [chunk(E2024, "4.5", "a 72-hour window")],
        E2025: [chunk(E2025, "4.5", "a 96-hour window")],
    }
    result = generate.generate("80 hours apart?", route, chunks)

    assert len(seen) == 2
    assert "96-hour" not in seen[0].split("Extracts:")[1]  # 2024's pass never sees 2025
    assert "72-hour" not in seen[1].split("Extracts:")[1]
    assert result.text == "combined"
    assert {c.doc_id for c in result.citations} == {E2024, E2025}
    assert all(c.verified for c in result.calculations)


def test_abstain_without_context_makes_no_model_call(monkeypatch):
    monkeypatch.setattr(generate, "structured_call", lambda *a: pytest.fail("called the model"))
    route = Route(
        mode=Mode.ABSTAIN,
        editions=(),
        reason="No held edition was in force.",
        abstain_reason="no_edition_in_force",
    )
    result = generate.generate("claim on 1 Feb 2026?", route, {})
    assert result.mode == "abstain" and "No held edition" in result.text
