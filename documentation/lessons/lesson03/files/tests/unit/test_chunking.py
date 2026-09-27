"""The Lesson 03 sanity checks, as tests. Chunking bugs present as retrieval bugs later."""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

import pytest

from dti_rag.ingestion.__main__ import build_chunks, serialise
from dti_rag.ingestion.chunk import chunk_key, reflow
from dti_rag.ingestion.parse import parse_pdf
from dti_rag.models import Chunk, ChunkKind, Status

ROOT = Path(__file__).resolve().parents[2]
PDFS = sorted((ROOT / "data" / "policy_documents").glob("*.pdf"))
MATRIX = ROOT / "data" / "fact_matrix" / "editions_fact_matrix.csv"


@pytest.fixture(scope="module")
def chunks() -> list[Chunk]:
    return build_chunks()


def find(chunks: list[Chunk], doc_id: str, section_id: str) -> list[Chunk]:
    return [
        c for c in chunks if c.metadata.doc_id == doc_id and c.metadata.section_id == section_id
    ]


def test_every_edition_is_chunked_with_comparable_counts(chunks):
    counts = Counter(c.metadata.doc_id for c in chunks)
    assert len(counts) == 5
    assert max(counts.values()) - min(counts.values()) <= 10, counts


def test_2024_excess_clause_is_exactly_one_chunk_saying_300(chunks):
    matches = [
        c for c in chunks if c.metadata.edition_year == 2024 and c.metadata.section_id == "3.4"
    ]
    assert len(matches) == 1
    assert "standard excess for an escape of water claim is £300" in matches[0].content


def test_section_8_exists_in_every_edition(chunks):
    for doc_id in {c.metadata.doc_id for c in chunks}:
        section_8 = [
            c for c in chunks if c.metadata.doc_id == doc_id and c.metadata.section_group == "8"
        ]
        assert section_8, doc_id
        year = section_8[0].metadata.edition_year
        text = " ".join(c.content for c in section_8)
        if year < 2024:
            assert "not offered" in text, doc_id
        else:
            assert "Home emergency" in text, doc_id


def test_section_3_6_is_a_decoy(chunks):
    (claims,) = find(chunks, "DTI-HOME-PW-2022-v1.0", "3.6")
    (fuel,) = find(chunks, "DTI-HOME-PW-2023-v1.0", "3.6")
    assert "Claims process" in claims.metadata.section_title
    assert "Escape of oil or fuel" in fuel.metadata.section_title


def test_section_9_is_renumbered_after_2022(chunks):
    (interact_2022,) = find(chunks, "DTI-HOME-PW-2022-v1.0", "9.6")
    (disease_2023,) = find(chunks, "DTI-HOME-PW-2023-v1.0", "9.6")
    assert "How exclusions interact" in interact_2022.metadata.section_title
    assert "Communicable disease" in disease_2023.metadata.section_title


def test_footers_are_gone(chunks):
    footer = re.compile(r"Page \d+ of \d+|DAVIDSTOWN INSURANCE|Status: [A-Z]{4}")
    assert not [c.id for c in chunks if footer.search(c.content)]


def test_bullets_are_rejoined(chunks):
    assert not [c.id for c in chunks if re.search(r"^–$", c.content, re.MULTILINE)]


def test_no_phantom_sections_from_the_contents_page(chunks):
    per_doc_sections = Counter((c.metadata.doc_id, c.id) for c in chunks)
    assert all(n == 1 for n in per_doc_sections.values())
    assert all(c.metadata.page >= 2 for c in chunks)


def test_excess_table_is_paired(chunks):
    (table,) = find(chunks, "DTI-HOME-PW-2025-v1.0", "10")
    assert table.metadata.chunk_kind == ChunkKind.EXCESS_SUMMARY
    assert "Escape of water (shower tray / wet room): £600" in table.content


def test_storm_definition_is_its_own_chunk(chunks):
    storm = [c for c in find(chunks, "DTI-HOME-PW-2022-v1.0", "1") if c.id.endswith("__storm")]
    assert len(storm) == 1 and "48 knots" in storm[0].content


def test_document_control_matches_the_qa_bank_section_name(chunks):
    (control,) = find(chunks, "DTI-HOME-PW-2022-v1.0", "Document control")
    assert "DTI-HOME-PW-2021-v1.0" in control.content  # the DTI-024 trap


def test_keys_are_legal_search_document_keys(chunks):
    assert all(re.fullmatch(r"[A-Za-z0-9_\-=]+", c.id) for c in chunks)
    assert chunk_key("DTI-HOME-PW-2024-v1.0", "3.4") == "DTI-HOME-PW-2024-v1_0__3_4"


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem)
def test_parsed_status_matches_footer_and_fact_matrix(pdf):
    doc = parse_pdf(pdf)
    with MATRIX.open(newline="", encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["doc_id"] == doc.doc_id)
    assert doc.footer_status == doc.status.value  # catches "SUPERSEDEDEffective"
    assert doc.status == Status(row["status"])


@pytest.mark.parametrize("pdf", PDFS, ids=lambda p: p.stem)
def test_edition_registry_in_fact_matrix_matches_the_pdf(pdf):
    """The one part of the fact matrix the router relies on (Lesson 07), verified."""
    doc = parse_pdf(pdf)
    with MATRIX.open(newline="", encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["doc_id"] == doc.doc_id)
    assert int(row["edition_year"]) == doc.edition_year
    assert row["version"] == doc.version
    assert row["effective_from"] == doc.control_fields["Effective from"]
    assert row["effective_to"] == doc.control_fields["Effective to"]
    assert row["supersedes"] == doc.control_fields["Supersedes"]


def test_output_is_byte_identical_across_runs():
    assert serialise(build_chunks()) == serialise(build_chunks())


def test_reflow_keeps_bullets_and_resumes_prose():
    text = reflow(["We cover:", "– a pipe;", "– a tank.", "This includes tracing", "costs."])
    assert text.splitlines() == [
        "We cover:",
        "– a pipe;",
        "– a tank.",
        "This includes tracing costs.",
    ]
