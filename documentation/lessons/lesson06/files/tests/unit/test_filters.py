from datetime import date

import pytest

from dti_rag.models import Status
from dti_rag.retrieval.filters import SearchFilter, by_date, by_doc, by_year, current


def test_date_filter_is_an_inclusive_range_on_real_dates():
    assert by_date(date(2024, 3, 15)).to_odata() == (
        "effective_from le 2024-03-15T00:00:00Z and effective_to ge 2024-03-15T00:00:00Z"
    )


@pytest.mark.parametrize("day", [date(2023, 6, 30), date(2023, 7, 1)])
def test_boundary_days_produce_midnight_comparisons(day):
    assert f"{day.isoformat()}T00:00:00Z" in by_date(day).to_odata()


def test_status_is_the_stored_upper_case_value():
    assert current().to_odata() == "status eq 'CURRENT'"


def test_year_and_doc_filters():
    assert by_year(2024).to_odata() == "edition_year eq 2024"
    assert by_doc("DTI-HOME-PW-2024-v1.0").to_odata() == "doc_id eq 'DTI-HOME-PW-2024-v1.0'"


def test_several_docs_use_search_in():
    f = SearchFilter(doc_ids=("DTI-HOME-PW-2024-v1.0", "DTI-HOME-PW-2025-v1.0"))
    assert f.to_odata() == ("search.in(doc_id, 'DTI-HOME-PW-2024-v1.0,DTI-HOME-PW-2025-v1.0', ',')")


def test_clauses_combine_with_and():
    f = SearchFilter(doc_ids=("DTI-HOME-PW-2025-v1.0",), section_group="3")
    assert f.to_odata() == "doc_id eq 'DTI-HOME-PW-2025-v1.0' and section_group eq '3'"


def test_empty_filter_is_none():
    assert SearchFilter().to_odata() is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"doc_ids": ("DTI-HOME-PW-2024-v1.0' or true or doc_id eq '",)},
        {"doc_ids": ("anything",)},
        {"edition_year": "2024 or 1 eq 1"},
        {"version": "1.0' or '1'='1"},
        {"status": "CURRENT' or status ne '"},
        {"section_group": "3' or section_group ne '"},
        {"loss_date": "2024-03-15"},
    ],
)
def test_untyped_or_malformed_values_never_reach_a_filter(kwargs):
    with pytest.raises(ValueError):
        SearchFilter(**kwargs)


def test_status_enum_is_accepted():
    assert SearchFilter(status=Status.ARCHIVED).to_odata() == "status eq 'ARCHIVED'"
