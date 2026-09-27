from datetime import date

import pytest

from dti_rag.models import Status
from dti_rag.query.editions import NoEditionInForce, is_ambiguous, load_registry

REG = load_registry()


@pytest.mark.parametrize(
    "day, doc_id",
    [
        (date(2022, 1, 1), "DTI-HOME-PW-2022-v1.0"),
        (date(2023, 6, 30), "DTI-HOME-PW-2023-v1.0"),  # last day of v1.0
        (date(2023, 7, 1), "DTI-HOME-PW-2023-v1.1"),  # first day of v1.1
        (date(2024, 3, 15), "DTI-HOME-PW-2024-v1.0"),  # DTI-004
        (date(2025, 12, 31), "DTI-HOME-PW-2025-v1.0"),
    ],
)
def test_a_date_resolves_to_exactly_one_edition(day, doc_id):
    assert REG.resolve_by_date(day).doc_id == doc_id


@pytest.mark.parametrize("day", [date(2021, 12, 31), date(2026, 1, 1)])
def test_dates_outside_every_held_edition_raise(day):
    with pytest.raises(NoEditionInForce):
        REG.resolve_by_date(day)


def test_2023_is_two_editions():
    editions = REG.resolve_by_year(2023)
    assert [e.version for e in editions] == ["1.0", "1.1"]
    assert is_ambiguous(editions)
    assert not is_ambiguous(REG.resolve_by_year(2024))


def test_version_resolution():
    assert REG.resolve_version(2023, "1.1").doc_id == "DTI-HOME-PW-2023-v1.1"
    assert REG.resolve_version(2024, "1.1") is None


def test_current_is_by_status_not_by_date():
    assert REG.current().doc_id == "DTI-HOME-PW-2025-v1.0"
    assert REG.current().status == Status.CURRENT


def test_the_2021_edition_is_referenced_but_not_held():
    assert REG.by_doc_id("DTI-HOME-PW-2021-v1.0") is None
    assert REG.superseding("DTI-HOME-PW-2021-v1.0").doc_id == "DTI-HOME-PW-2022-v1.0"


def test_registry_rejects_gaps():
    from dataclasses import replace

    from dti_rag.query.editions import EditionRegistry

    broken = list(REG.editions)
    broken[1] = replace(broken[1], effective_from=date(2023, 1, 2))
    with pytest.raises(ValueError, match="gap or overlap"):
        EditionRegistry(broken)
