"""The one path every answer takes: route -> retrieve -> generate.

The API (Lesson 12), the eval harness (Lesson 10) and anything else that answers a question
calls answer(). The moment an evaluator calls a different code path from the one you ship,
you're evaluating something you don't ship.

Lesson 09 added two branches, designed as LangGraph nodes and ported here as plain code:
clause-by-clause comparison, and the post-retrieval ambiguity check.
"""

from __future__ import annotations

from dataclasses import dataclass

from dti_rag.generation.compare import compare, resolve_after_retrieval
from dti_rag.generation.crossref import follow_ups
from dti_rag.generation.generate import generate
from dti_rag.models import Answer, RetrievedChunk
from dti_rag.query.router import Mode, Route, route
from dti_rag.retrieval.filters import SearchFilter
from dti_rag.retrieval.retrieve import RetrievalConfig, RetrievalResult, all_chunks, retrieve

FOLLOW_UP = RetrievalConfig(k=4)
ABSTAIN_CONTEXT = RetrievalConfig(k=3)  # just enough to cite the nearest clause


@dataclass
class PipelineResult:
    answer: Answer
    route: Route
    retrievals: list[RetrievalResult]

    @property
    def chunks(self) -> list[RetrievedChunk]:
        seen: dict[str, RetrievedChunk] = {}
        for r in self.retrievals:
            for c in r.chunks:
                seen.setdefault(c.id, c)
        return list(seen.values())


def is_comparison(chosen: Route) -> bool:
    return (
        chosen.mode == Mode.ANSWER
        and chosen.question_type == "comparison"
        and len(chosen.editions) >= 2
    )


def retrieve_for_route(question: str, chosen: Route) -> list[RetrievalResult]:
    """One retrieval per edition in scope, plus same-edition follow-ups for signposts."""
    if is_comparison(chosen):
        # A diff needs every clause of each edition, not the top-k most similar ones.
        return [
            RetrievalResult(query="*", filter=f.to_odata(), chunks=all_chunks(e.doc_id))
            for e, f in zip(chosen.editions, chosen.filters(), strict=True)
        ]
    config = ABSTAIN_CONTEXT if chosen.abstain_reason else RetrievalConfig()
    results: list[RetrievalResult] = []
    for edition_filter in chosen.filters():
        first = retrieve(question, edition_filter, config)
        results.append(first)
        for doc_id, group in follow_ups(first.chunks):
            # A cross-reference is internal to a document: never follow it into another edition.
            results.append(
                retrieve(question, SearchFilter(doc_ids=(doc_id,), section_group=group), FOLLOW_UP)
            )
    return results


def group_by_edition(
    chosen: Route, retrievals: list[RetrievalResult]
) -> dict[str, list[RetrievedChunk]]:
    by_edition: dict[str, list[RetrievedChunk]] = {e.doc_id: [] for e in chosen.editions}
    for result in retrievals:
        for chunk in result.chunks:
            bucket = by_edition.setdefault(chunk.doc_id, [])
            if chunk.id not in {c.id for c in bucket}:
                bucket.append(chunk)
    return by_edition


def answer(question: str) -> PipelineResult:
    chosen = route(question)
    retrievals = retrieve_for_route(question, chosen)
    by_edition = group_by_edition(chosen, retrievals)
    if is_comparison(chosen):
        generated = compare(question, chosen, by_edition)
    else:
        chosen = resolve_after_retrieval(chosen, by_edition)
        generated = generate(question, chosen, by_edition)
    return PipelineResult(answer=generated, route=chosen, retrievals=retrievals)
