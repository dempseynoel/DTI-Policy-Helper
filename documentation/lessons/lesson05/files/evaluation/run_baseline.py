"""Run the naive baseline over all 25 questions and record exactly how it fails.

    make baseline ENV=dev

Writes evaluation/baselines/naive-baseline-<env>.json (commit it: Lesson 10 compares against
it and Lesson 13 regenerates it in test) and prints the per-question diagnosis that goes into
documentation/design/baseline_failures.md.
"""

from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path

from dti_rag.clients import throttled_response_count
from dti_rag.config import get_settings
from dti_rag.retrieval.baseline import PROMPT_VERSION, answer_naive
from evaluation.checks import gold_doc_retrieved, missing_includes, present_excludes, section_hit
from evaluation.qa_bank import load_bank
from evaluation.rows import RetrievedRef, Run, RunRow
from evaluation.runmeta import collect_meta

BASELINES = Path(__file__).resolve().parent / "baselines"


def main() -> None:
    settings = get_settings()
    meta = collect_meta(
        settings, target="local", pipeline="baseline", prompt_version=PROMPT_VERSION
    )
    rows: list[RunRow] = []
    for item in load_bank():
        started = time.perf_counter()
        result = answer_naive(item.question)
        rows.append(
            RunRow(
                qa_id=item.id,
                category=item.category,
                question=item.question,
                pipeline="baseline",
                mode="answer",
                answer=result.answer,
                retrieved=[
                    RetrievedRef(doc_id=c.doc_id, section_id=c.section_id, score=c.score)
                    for c in result.chunks
                ],
                contexts=[c.content for c in result.chunks],
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        )
        print(f"  {item.id} done")
    meta.throttled_responses = throttled_response_count()
    out = BASELINES / f"naive-baseline-{settings.app_env}.json"
    Run(meta=meta, rows=rows).save(out)
    print(f"\nwrote {out}\n")
    report(rows)


def report(rows: list[RunRow]) -> None:
    bank = {item.id: item for item in load_bank()}
    by_category: dict[str, list[bool]] = defaultdict(list)
    print(
        "| QA ID | Category | Gold doc retrieved? | Gold section retrieved? "
        "| Missing | Wrong values present |"
    )
    print("|---|---|---|---|---|---|")
    for row in rows:
        item = bank[row.qa_id]
        docs = [r.doc_id for r in row.retrieved]
        pairs = [(r.doc_id, r.section_id) for r in row.retrieved]
        missing = missing_includes(row.answer, item.must_include)
        wrong = present_excludes(row.answer, item.must_not_include)
        by_category[item.category].append(not missing and not wrong)
        print(
            f"| {item.id} | {item.category} "
            f"| {'yes' if gold_doc_retrieved(docs, item.gold_doc_ids) else 'NO'} "
            f"| {'yes' if section_hit(pairs, item.gold_doc_ids, item.gold_sections) else 'NO'} "
            f"| {', '.join(missing) or '—'} | {', '.join(wrong) or '—'} |"
        )
    print("\nmust_include + must_not_include pass rate by category:")
    for category, results in sorted(by_category.items()):
        print(f"  {category:28} {sum(results)}/{len(results)}")


if __name__ == "__main__":
    main()
