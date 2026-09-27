"""decide() is the edition-selection policy. Tested with hand-built extractions: no LLM."""

from dti_rag.query.editions import load_registry
from dti_rag.query.extract import Extraction, NamedEdition
from dti_rag.query.router import FRESHNESS_NOTE, Mode, decide

REG = load_registry()


def ex(**kwargs) -> Extraction:
    return Extraction.empty().model_copy(update=kwargs)


def docs(route):
    return [e.doc_id for e in route.editions]


def test_dti_004_loss_date_selects_2024():
    route = decide(ex(loss_date="2024-03-15"), REG)
    assert route.mode == Mode.ANSWER
    assert docs(route) == ["DTI-HOME-PW-2024-v1.0"]
    assert "15 March 2024" in route.reason and "1 January 2024" in route.reason


def test_dti_006_date_resolves_the_2023_split_so_no_ambiguity():
    route = decide(
        ex(loss_date="2023-05-03", named_editions=[NamedEdition(year=2023, version=None)]), REG
    )
    assert route.mode == Mode.ANSWER
    assert docs(route) == ["DTI-HOME-PW-2023-v1.0"]


def test_dti_008_bare_2023_asks():
    route = decide(ex(named_editions=[NamedEdition(year=2023, version=None)]), REG)
    assert route.mode == Mode.ASK
    assert docs(route) == ["DTI-HOME-PW-2023-v1.0", "DTI-HOME-PW-2023-v1.1"]
    assert "30 June 2023" in route.reason and "1 July 2023" in route.reason


def test_dti_010_freshness_default_carries_its_caveat():
    route = decide(ex(), REG)
    assert route.mode == Mode.ANSWER
    assert docs(route) == ["DTI-HOME-PW-2025-v1.0"]
    assert FRESHNESS_NOTE in route.notes


def test_dti_015_two_named_years_answer_per_edition():
    named = [NamedEdition(year=2024, version=None), NamedEdition(year=2025, version=None)]
    route = decide(ex(named_editions=named), REG)
    assert route.mode == Mode.ANSWER
    assert docs(route) == ["DTI-HOME-PW-2024-v1.0", "DTI-HOME-PW-2025-v1.0"]
    assert len(route.filters()) == 2


def test_dti_017_second_2023_edition_is_v1_1():
    named = [NamedEdition(year=2023, version="1.1"), NamedEdition(year=2024, version=None)]
    route = decide(ex(named_editions=named), REG)
    assert route.mode == Mode.ANSWER
    assert docs(route) == ["DTI-HOME-PW-2023-v1.1", "DTI-HOME-PW-2024-v1.0"]


def test_dti_012_existence_questions_check_every_edition():
    route = decide(ex(question_type="existence_or_history"), REG)
    assert route.mode == Mode.ANSWER
    assert len(route.editions) == 5


def test_dti_024_unheld_document_abstains_and_points_at_2022():
    route = decide(ex(referenced_doc_ids=["DTI-HOME-PW-2021-v1.0"]), REG)
    assert route.mode == Mode.ABSTAIN
    assert route.abstain_reason == "out_of_corpus"
    assert docs(route) == ["DTI-HOME-PW-2022-v1.0"]


def test_unheld_year_abstains():
    route = decide(ex(named_editions=[NamedEdition(year=2021, version=None)]), REG)
    assert route.mode == Mode.ABSTAIN


def test_dti_025_other_insurance_abstains():
    route = decide(ex(scope="other_insurance"), REG)
    assert route.mode == Mode.ABSTAIN
    assert route.abstain_reason == "out_of_scope"


def test_a_loss_date_after_the_current_edition_expired_abstains():
    route = decide(ex(loss_date="2026-02-01"), REG)
    assert route.mode == Mode.ABSTAIN
    assert route.abstain_reason == "no_edition_in_force"


def test_an_unparseable_date_is_dropped_not_guessed():
    route = decide(ex(loss_date="18 days"), REG)
    assert route.mode == Mode.ANSWER
    assert FRESHNESS_NOTE in route.notes


def test_a_plain_lookup_does_not_over_abstain():
    route = decide(ex(question_type="lookup"), REG)
    assert route.mode == Mode.ANSWER
