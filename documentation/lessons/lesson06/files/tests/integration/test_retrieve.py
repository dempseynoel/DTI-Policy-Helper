"""The test that matters: EVERY returned chunk is from the right edition, not just the top one.

One leaked 2025 chunk in the context is enough for the generator to pick £350.
"""

from datetime import date

import pytest

from dti_rag.retrieval.filters import by_date, current
from dti_rag.retrieval.retrieve import RetrievalConfig, retrieve

pytestmark = pytest.mark.integration


def doc_ids(result):
    return {c.doc_id for c in result.chunks}


def test_dated_2024_query_returns_only_2024_chunks():
    result = retrieve("what excess applies to a burst dishwasher hose?", by_date(date(2024, 3, 15)))
    assert result.chunks
    assert doc_ids(result) == {"DTI-HOME-PW-2024-v1.0"}


@pytest.mark.parametrize(
    "day, expected",
    [
        (date(2023, 6, 30), "DTI-HOME-PW-2023-v1.0"),
        (date(2023, 7, 1), "DTI-HOME-PW-2023-v1.1"),
    ],
)
def test_both_sides_of_the_2023_boundary(day, expected):
    assert doc_ids(retrieve("pedal cycle theft limit", by_date(day))) == {expected}


def test_current_returns_only_the_current_edition():
    assert doc_ids(retrieve("standard excess", current())) == {"DTI-HOME-PW-2025-v1.0"}


def test_prefilter_finds_the_minority_value():
    """DTI-003: with the filter, the 2022 storm definition is in the candidate set."""
    result = retrieve(
        "wind speed needed for a storm",
        by_date(date(2022, 6, 1)),
        RetrievalConfig(hybrid=False, semantic=False, k=3),
    )
    assert any("48 knots" in c.content for c in result.chunks)


def test_semantic_ranking_is_available_in_this_environment():
    result = retrieve("tiles blew off and rain came in", current())
    assert result.chunks[0].reranker_score is not None
