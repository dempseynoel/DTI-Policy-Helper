"""What gets evaluated. Both targets emit the same RunRow; scoring never knows which ran.

- local: pipeline.answer() in-process. Fast. Lesson 13's PR gate.
- api:   a deployed POST /chat. Proves the deployed system: container, identity, config,
         index. Lesson 13's promotion gate.
- baseline: the naive Lesson 05 pipeline, in-process. The control group.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Protocol

import httpx

from evaluation.checks import section_hit
from evaluation.qa_bank import QAItem
from evaluation.rows import RetrievedRef, RunRow


class Target(Protocol):
    name: str
    pipeline: str

    def run(self, item: QAItem) -> RunRow: ...


def _row(item: QAItem, pipeline: str, **fields) -> RunRow:
    return RunRow(
        qa_id=item.id, category=item.category, question=item.question, pipeline=pipeline, **fields
    )


class BaselineTarget:
    name, pipeline = "local", "baseline"

    def run(self, item: QAItem) -> RunRow:
        from dti_rag.retrieval.baseline import answer_naive

        started = time.perf_counter()
        result = answer_naive(item.question)
        return _row(
            item,
            self.pipeline,
            mode="answer",
            answer=result.answer,
            retrieved=[
                RetrievedRef(doc_id=c.doc_id, section_id=c.section_id, score=c.score)
                for c in result.chunks
            ],
            contexts=[c.content for c in result.chunks],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class LocalTarget:
    name, pipeline = "local", "current"

    def run(self, item: QAItem) -> RunRow:
        from dti_rag.pipeline import answer

        started = time.perf_counter()
        result = answer(item.question)
        a = result.answer
        row = _row(
            item,
            self.pipeline,
            mode=a.mode,
            answer=a.text,
            retrieved=[
                RetrievedRef(
                    doc_id=c.doc_id, section_id=c.section_id, score=c.reranker_score or c.score
                )
                for c in result.chunks
            ],
            contexts=[c.content for c in result.chunks],
            citations=[c.model_dump(mode="json") for c in a.citations],
            governing_editions=a.governing_editions,
            route_reason=a.edition_reason,
            guardrail_status=a.guardrail_status,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        if item.query_date:
            row.probe_filtered_hit, row.probe_unfiltered_hit = probe_dated_retrieval(item)
        return row


def probe_dated_retrieval(item: QAItem) -> tuple[bool, bool]:
    """The headline number: the same question, with and without the loss-date pre-filter."""
    from dti_rag.retrieval.filters import by_date
    from dti_rag.retrieval.retrieve import retrieve

    def hit(result) -> bool:
        pairs = [(c.doc_id, c.section_id) for c in result.chunks]
        pure = {c.doc_id for c in result.chunks} <= set(item.gold_doc_ids)
        return section_hit(pairs, item.gold_doc_ids, item.gold_sections) and pure

    day = date.fromisoformat(item.query_date)
    return hit(retrieve(item.question, by_date(day))), hit(retrieve(item.question, None))


class ApiTarget:
    """Calls a deployed /chat. The response contract is Lesson 12's ChatResponse.

    Retrieved context isn't in the response. Lesson 13 reads it back from the audit log by
    trace_id, so every promotion also proves the audit trail is complete.
    """

    name, pipeline = "api", "current"

    def __init__(self, base_url: str, token: str | None = None, context_reader=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.client = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=120)
        self.context_reader = context_reader

    def run(self, item: QAItem) -> RunRow:
        started = time.perf_counter()
        response = self.client.post("/chat", json={"question": item.question})
        response.raise_for_status()
        body = response.json()
        contexts: list[str] = []
        retrieved: list[RetrievedRef] = []
        if self.context_reader and body.get("trace_id"):
            record = self.context_reader(body["trace_id"])
            contexts = [c["content"] for c in record["chunks"]]
            retrieved = [
                RetrievedRef(doc_id=c["doc_id"], section_id=c["section_id"])
                for c in record["chunks"]
            ]
        return _row(
            item,
            self.pipeline,
            mode=body["mode"],
            answer=body["answer"],
            retrieved=retrieved,
            contexts=contexts,
            citations=body["citations"],
            governing_editions=body["governing_editions"],
            route_reason=body["edition_reason"],
            guardrail_status=body.get("guardrail_status"),
            trace_id=body.get("trace_id"),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
