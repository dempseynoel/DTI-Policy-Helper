"""The 25-question bank: ground truth for scoring, never for answering."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

BANK = Path(__file__).resolve().parents[1] / "data" / "question_answers" / "dti_rag_qa_bank.jsonl"


class QAItem(BaseModel):
    id: str
    category: str
    difficulty: str
    question: str
    answer: str
    gold_doc_ids: list[str]
    gold_sections: list[str]
    fact_keys: list[str]
    must_include: list[str]
    must_not_include: list[str]
    ambiguous: bool
    answerable: bool
    query_date: str | None
    expected_behaviour: str
    tests: str


def load_bank(path: Path = BANK) -> list[QAItem]:
    with path.open(encoding="utf-8") as f:
        return [QAItem.model_validate_json(line) for line in f if line.strip()]
