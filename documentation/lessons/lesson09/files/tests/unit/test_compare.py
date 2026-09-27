"""The DTI-022 trap, offline: diff the real wording and find what the summary left out."""

from __future__ import annotations

import pytest

from dti_rag.generation.compare import body, diff_editions, resolve_after_retrieval
from dti_rag.ingestion.__main__ import build_chunks
from dti_rag.models import RetrievedChunk
from dti_rag.query.editions import load_registry
from dti_rag.query.router import ASK_NOTE, Mode, Route

REG = load_registry()


@pytest.fixture(scope="module")
def editions() -> dict[str, list[RetrievedChunk]]:
    out: dict[str, list[RetrievedChunk]] = {}
    for c in build_chunks():
        m = c.metadata
        out.setdefault(m.doc_id, []).append(
            RetrievedChunk(
                id=c.id,
                content=c.content,
                **m.model_dump(
                    include={
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
                    }
                ),
            )
        )
    return out


def test_the_diff_finds_the_four_changes_the_2025_summary_omits(editions):
    changes = diff_editions(editions["DTI-HOME-PW-2024-v1.0"], editions["DTI-HOME-PW-2025-v1.0"])
    after = {c.key: body(c.new) for c in changes if c.new}
    summary = next(
        c for c in editions["DTI-HOME-PW-2025-v1.0"] if c.section_id == "Document control"
    )

    omitted = {
        "4.2": "£2,000",  # outbuildings £1,500 -> £2,000
        "4.6": "£1,000",  # emergency repairs £750 -> £1,000
        "7.6": "£200",  # accidental damage excess £150 -> £200
        "8.1": "£1,500",  # home emergency £1,000 -> £1,500
    }
    for key, figure in omitted.items():
        assert figure in after[key], key
    assert "£200" not in body(summary) and "outbuildings" not in body(summary).lower()


def test_clauses_new_in_2025_are_reported_as_added(editions):
    changes = diff_editions(editions["DTI-HOME-PW-2024-v1.0"], editions["DTI-HOME-PW-2025-v1.0"])
    added = {c.key for c in changes if c.kind == "added"}
    assert "1:flood-re" in added  # new definition
    assert "7.4" not in added or "charging" in body(next(c.new for c in changes if c.key == "7.4"))


def test_the_change_summary_is_never_diffed_as_a_clause(editions):
    changes = diff_editions(editions["DTI-HOME-PW-2024-v1.0"], editions["DTI-HOME-PW-2025-v1.0"])
    assert all(c.key != "Document control" for c in changes)


def ask_route(*doc_ids: str) -> Route:
    return Route(
        mode=Mode.ASK,
        editions=tuple(REG.by_doc_id(d) for d in doc_ids),
        reason="2023 has two editions.",
        notes=(ASK_NOTE,),
    )


def test_editions_that_word_a_clause_identically_are_not_ambiguous(editions):
    v10, v11 = "DTI-HOME-PW-2023-v1.0", "DTI-HOME-PW-2023-v1.1"
    police = {d: [c for c in editions[d] if c.section_id == "6.7"] for d in (v10, v11)}
    resolved = resolve_after_retrieval(ask_route(v10, v11), police)
    assert resolved.mode == Mode.ANSWER
    assert ASK_NOTE not in resolved.notes


def test_editions_that_disagree_stay_ambiguous(editions):
    v10, v11 = "DTI-HOME-PW-2023-v1.0", "DTI-HOME-PW-2023-v1.1"
    cycles = {d: [c for c in editions[d] if c.section_id == "6.3"] for d in (v10, v11)}
    assert resolve_after_retrieval(ask_route(v10, v11), cycles).mode == Mode.ASK
