from evaluation.checks import (
    contains,
    gold_doc_retrieved,
    missing_includes,
    present_excludes,
    section_hit,
)
from evaluation.qa_bank import load_bank


def test_figures_match_exactly():
    assert contains("The excess is £300.", "£300")
    assert not contains("The excess is 300 pounds.", "£300")
    assert not contains("The excess is £3,000.", "£300")  # note: substring would be a bug


def test_short_words_match_whole_words_only():
    assert contains("It is not covered.", "not")
    assert not contains("Please note the schedule.", "not")
    assert not contains("We cannot say.", "not")


def test_case_and_whitespace_are_normalised():
    assert contains("Assessed under\nsection   3.", "Section 3")


def test_must_include_and_must_not_include():
    answer = "£300 under the 2024 edition."
    assert missing_includes(answer, ["£300", "2024"]) == []
    assert present_excludes(answer, ["£350", "£250"]) == []
    assert present_excludes("£350", ["£350"]) == ["£350"]


def test_section_hit_needs_the_doc_and_section_pair():
    gold_docs, gold_sections = ["DTI-HOME-PW-2024-v1.0"], ["3.4", "10"]
    assert section_hit([("DTI-HOME-PW-2024-v1.0", "3.4")], gold_docs, gold_sections)
    assert not section_hit([("DTI-HOME-PW-2025-v1.0", "3.4")], gold_docs, gold_sections)
    assert section_hit([("DTI-HOME-PW-2024-v1.0", "4.1")], gold_docs, ["4"])
    assert not section_hit([("DTI-HOME-PW-2024-v1.0", "10")], gold_docs, ["1"])


def test_gold_doc_retrieved():
    assert gold_doc_retrieved(["a", "b"], ["b"])
    assert not gold_doc_retrieved(["a"], ["b"])


def test_bank_loads_all_25_questions():
    bank = load_bank()
    assert len(bank) == 25
    assert {i.category for i in bank} >= {"abstention_out_of_corpus", "abstention_out_of_scope"}
