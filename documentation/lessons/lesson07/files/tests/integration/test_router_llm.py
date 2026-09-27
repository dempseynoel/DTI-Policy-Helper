"""The LLM half of the router, against the real `chat` deployment.

Tool-calling behaviour is a property of the model version. These tests run in test against
the same version prod uses, so a model upgrade is caught as a router change.
"""

import pytest

from dti_rag.query.router import Mode, route
from evaluation.qa_bank import load_bank

pytestmark = pytest.mark.integration
BANK = {item.id: item for item in load_bank()}


def q(qa_id: str) -> str:
    return BANK[qa_id].question


def test_dti_004_extracts_the_loss_date():
    r = route(q("DTI-004"))
    assert r.extraction.loss_date == "2024-03-15"
    assert [e.doc_id for e in r.editions] == ["DTI-HOME-PW-2024-v1.0"]


def test_dti_017_duration_is_not_a_date():
    r = route(q("DTI-017"))
    assert r.extraction.loss_date is None
    assert [e.doc_id for e in r.editions] == ["DTI-HOME-PW-2023-v1.1", "DTI-HOME-PW-2024-v1.0"]


@pytest.mark.parametrize(
    "qa_id, mode",
    [
        ("DTI-006", Mode.ANSWER),
        ("DTI-008", Mode.ASK),
        ("DTI-010", Mode.ANSWER),
        ("DTI-015", Mode.ANSWER),
        ("DTI-024", Mode.ABSTAIN),
        ("DTI-025", Mode.ABSTAIN),
    ],
)
def test_modes(qa_id, mode):
    assert route(q(qa_id)).mode == mode
