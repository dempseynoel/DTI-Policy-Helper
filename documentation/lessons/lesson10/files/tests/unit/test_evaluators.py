"""The evaluators and the gate, offline, on hand-built rows."""

from evaluation.compare import comparable, gate
from evaluation.evaluators import (
    abstention_correct,
    ambiguity_handled,
    edition_correct,
    over_abstained,
    weak_includes,
)
from evaluation.qa_bank import load_bank
from evaluation.rows import RetrievedRef, Run, RunMeta, RunRow
from evaluation.scorecard import score

BANK = {i.id: i for i in load_bank()}
E2024, E2025 = "DTI-HOME-PW-2024-v1.0", "DTI-HOME-PW-2025-v1.0"


def row(qa_id: str, **fields) -> RunRow:
    item = BANK[qa_id]
    defaults = dict(
        qa_id=qa_id,
        category=item.category,
        question=item.question,
        pipeline="current",
        mode="answer",
        answer="",
    )
    return RunRow(**{**defaults, **fields})


def meta(**overrides) -> RunMeta:
    base = dict(
        app_env="test",
        target="local",
        pipeline="current",
        prompt_version="gen-v2",
        git_sha="abc",
        started_at="now",
        serving_models={
            "chat": {"model": "m", "version": "1"},
            "embed": {"model": "e", "version": "1"},
        },
        index_manifest={"schema_version": 1, "embed_model_version": "1"},
    )
    return RunMeta(**{**base, **overrides})


def test_edition_correct_catches_a_grounded_wrong_edition_answer():
    right = row("DTI-004", governing_editions=[E2024], citations=[{"doc_id": E2024}], answer="£300")
    wrong = row("DTI-004", governing_editions=[E2025], citations=[{"doc_id": E2025}], answer="£350")
    assert edition_correct(right, BANK["DTI-004"]) is True
    assert edition_correct(wrong, BANK["DTI-004"]) is False


def test_edition_correct_catches_contamination():
    contaminated = row(
        "DTI-004", governing_editions=[E2024], citations=[{"doc_id": E2024}, {"doc_id": E2025}]
    )
    assert edition_correct(contaminated, BANK["DTI-004"]) is False


def test_edition_correct_falls_back_to_doc_ids_in_the_text_for_the_baseline():
    baseline = row("DTI-004", pipeline="baseline", answer=f"Per {E2025}, £350.")
    assert edition_correct(baseline, BANK["DTI-004"]) is False


def test_abstention_needs_the_mode_and_no_figure():
    assert abstention_correct(
        row("DTI-024", mode="abstain", answer="The 2021 edition is not held."), BANK["DTI-024"]
    )
    assert not abstention_correct(
        row("DTI-024", mode="abstain", answer="Not held, but probably £250."), BANK["DTI-024"]
    )
    assert not abstention_correct(
        row("DTI-024", mode="answer", answer="Not held."), BANK["DTI-024"]
    )
    assert abstention_correct(row("DTI-004"), BANK["DTI-004"]) is None


def test_over_abstention_is_measured():
    assert over_abstained(row("DTI-004", mode="abstain"), BANK["DTI-004"]) is True


def test_a_single_right_value_fails_an_ambiguous_question():
    single = row("DTI-008", citations=[{"doc_id": "DTI-HOME-PW-2023-v1.1"}], answer="£600")
    both = row("DTI-008", mode="ask", answer="£500 (v1.0) or £600 (v1.1): what was the loss date?")
    assert ambiguity_handled(single, BANK["DTI-008"]) is False
    assert ambiguity_handled(both, BANK["DTI-008"]) is True


def test_weak_must_include_entries_are_flagged():
    assert "not" in weak_includes(BANK["DTI-007"])


def test_scorecard_separates_retrieval_generation_and_behaviour():
    rows = [
        row(
            "DTI-004",
            governing_editions=[E2024],
            citations=[{"doc_id": E2024}],
            answer="£300 under the 2024 edition",
            retrieved=[RetrievedRef(doc_id=E2024, section_id="3.4")],
            probe_filtered_hit=True,
            probe_unfiltered_hit=False,
        ),
        row("DTI-024", mode="abstain", answer="The 2021 edition is not held."),
    ]
    card = score(Run(meta=meta(), rows=rows), list(BANK.values()))
    assert card.metrics["retrieval_section_hit"] == 1.0
    assert card.metrics["edition_correct"] == 1.0
    assert card.metrics["abstention_correct"] == 1.0
    assert card.metrics["probe_filtered_hit"] == 1.0 and card.metrics["probe_unfiltered_hit"] == 0.0


def test_gate_refuses_to_compare_different_model_versions():
    a = score(Run(meta=meta(), rows=[]), list(BANK.values()))
    b = score(
        Run(meta=meta(serving_models={"chat": {"model": "m", "version": "2"}}), rows=[]),
        list(BANK.values()),
    )
    assert comparable(a, b)
    passed, verdict = gate(a, b)
    assert not passed and "Not comparable" in verdict


def test_gate_has_zero_tolerance_on_edition_correct():
    good = row(
        "DTI-004", governing_editions=[E2024], citations=[{"doc_id": E2024}], answer="£300 2024"
    )
    bad = row(
        "DTI-004", governing_editions=[E2025], citations=[{"doc_id": E2025}], answer="£350 2025"
    )
    reference = score(Run(meta=meta(), rows=[good]), list(BANK.values()))
    candidate = score(Run(meta=meta(), rows=[bad]), list(BANK.values()))
    passed, verdict = gate(reference, candidate)
    assert not passed and "edition_correct regressed on DTI-004" in verdict
    assert gate(reference, reference)[0]


def test_scorecard_renders_with_and_without_a_reference():
    good = row(
        "DTI-004", governing_editions=[E2024], citations=[{"doc_id": E2024}], answer="£300 2024"
    )
    card = score(Run(meta=meta(), rows=[good]), list(BANK.values()))
    from evaluation.scorecard import render

    assert "edition_correct" in render(card)
    assert "Reference" in render(card, card)


def test_a_reference_recorded_before_the_judge_existed_is_still_comparable():
    before = score(Run(meta=meta(), rows=[]), list(BANK.values()))
    with_judge = meta(
        serving_models={
            "chat": {"model": "m", "version": "1"},
            "embed": {"model": "e", "version": "1"},
            "judge": {"model": "j", "version": "1"},
        }
    )
    after = score(Run(meta=with_judge, rows=[]), list(BANK.values()))
    assert comparable(before, after) == []
