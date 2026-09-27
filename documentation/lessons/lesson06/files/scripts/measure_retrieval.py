"""Add the Lesson 06 upgrades one at a time and measure what each bought.

    APP_ENV=dev python scripts/measure_retrieval.py

Filters are passed BY HAND here, from the QA bank's query_date and a few hand-written
edition choices. Choosing filters automatically is Lesson 07's router; until then, this is
what you'd type.
"""

from __future__ import annotations

from datetime import date

from dti_rag.retrieval.filters import SearchFilter, by_date, by_year, current
from dti_rag.retrieval.retrieve import RetrievalConfig, retrieve
from evaluation.checks import gold_doc_retrieved, section_hit
from evaluation.qa_bank import QAItem, load_bank

CATEGORIES = {"single_fact_lookup", "temporal_disambiguation", "paraphrase_robustness"}

# What a human would pick for the questions that name an edition or mean "current".
HAND_FILTERS: dict[str, SearchFilter] = {
    "DTI-001": by_year(2024),
    "DTI-002": current(),
    "DTI-003": by_year(2022),
}

CONFIGS = {
    "vector only": (RetrievalConfig(hybrid=False, semantic=False), False),
    "+ filters": (RetrievalConfig(hybrid=False, semantic=False), True),
    "+ hybrid": (RetrievalConfig(hybrid=True, semantic=False), True),
    "+ semantic": (RetrievalConfig(hybrid=True, semantic=True), True),
}


def hand_filter(item: QAItem) -> SearchFilter | None:
    if item.query_date:
        return by_date(date.fromisoformat(item.query_date))
    return HAND_FILTERS.get(item.id)


def main() -> None:
    items = [i for i in load_bank() if i.category in CATEGORIES]
    header = ("config", "gold doc in top-8", "gold section in top-8", "only gold docs")
    print(f"{header[0]:14} {header[1]:>18} {header[2]:>22} {header[3]:>15}")
    for label, (config, use_filters) in CONFIGS.items():
        doc_hits = section_hits = pure = 0
        for item in items:
            result = retrieve(item.question, hand_filter(item) if use_filters else None, config)
            docs = [c.doc_id for c in result.chunks]
            pairs = [(c.doc_id, c.section_id) for c in result.chunks]
            doc_hits += gold_doc_retrieved(docs, item.gold_doc_ids)
            section_hits += section_hit(pairs, item.gold_doc_ids, item.gold_sections)
            pure += bool(docs) and set(docs) <= set(item.gold_doc_ids)
        n = len(items)
        print(f"{label:14} {doc_hits:>15}/{n} {section_hits:>19}/{n} {pure:>12}/{n}")
    print(
        "\n'only gold docs' is the number that matters for generation: one wrong-edition chunk"
        "\nin the context is enough for the model to pick the wrong figure."
    )


if __name__ == "__main__":
    main()
