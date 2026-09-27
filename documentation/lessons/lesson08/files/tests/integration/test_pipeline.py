"""Lesson 08's 'done when', against a live environment."""

import pytest

from dti_rag.pipeline import answer
from evaluation.checks import missing_includes, present_excludes
from evaluation.qa_bank import load_bank

pytestmark = pytest.mark.integration
BANK = {item.id: item for item in load_bank()}


@pytest.mark.parametrize("qa_id", ["DTI-014", "DTI-015", "DTI-016", "DTI-018"])
def test_generation_traps(qa_id):
    item = BANK[qa_id]
    result = answer(item.question)
    assert missing_includes(result.answer.text, item.must_include) == []
    assert present_excludes(result.answer.text, item.must_not_include) == []


def test_every_citation_resolves_to_a_retrieved_chunk():
    result = answer(BANK["DTI-004"].question)
    retrieved = {(c.doc_id, c.section_id) for c in result.chunks}
    assert result.answer.citations
    assert all((c.doc_id, c.section_id) in retrieved for c in result.answer.citations)
