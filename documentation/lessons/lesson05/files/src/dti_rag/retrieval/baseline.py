"""The naive baseline: embed, vector top-k with no filters, stuff, generate.

    ┌──────────────────────────────────────────────────────────────────────┐
    │ THIS FILE MUST NEVER BE IMPROVED.                                    │
    │ Its job is to stay naive so Lesson 10's scorecard has an honest      │
    │ control group. A "quick fix" here makes every later comparison lie.  │
    └──────────────────────────────────────────────────────────────────────┘

The prompt is what a competent engineer writes on day one. It is deliberately not hobbled:
a rigged baseline is as meaningless as an improved one.
"""

from __future__ import annotations

from dataclasses import dataclass

from azure.search.documents.models import VectorizedQuery

from dti_rag.clients import openai_client, search_client
from dti_rag.config import get_settings
from dti_rag.models import RetrievedChunk
from dti_rag.retrieval.results import SELECT_FIELDS, to_retrieved
from dti_rag.search.schema import index_name

PROMPT_VERSION = "baseline-v1"
TOP_K = 5
SYSTEM_PROMPT = (
    "You are an assistant for insurance claims handlers. Answer the question using only the "
    "context provided. If the context does not contain the answer, say that you don't know."
)


@dataclass(frozen=True)
class BaselineResult:
    answer: str
    chunks: list[RetrievedChunk]


def retrieve_naive(question: str, k: int = TOP_K) -> list[RetrievedChunk]:
    settings = get_settings()
    vector = (
        openai_client()
        .embeddings.create(model=settings.azure_openai_embed_deployment, input=question)
        .data[0]
        .embedding
    )
    results = search_client(index_name(settings)).search(
        search_text=None,
        vector_queries=[
            VectorizedQuery(vector=vector, k_nearest_neighbors=k, fields="contentVector")
        ],
        select=SELECT_FIELDS,
        top=k,
    )
    return [to_retrieved(r) for r in results]


def answer_naive(question: str) -> BaselineResult:
    settings = get_settings()
    chunks = retrieve_naive(question)
    context = "\n\n---\n\n".join(c.content for c in chunks)
    response = openai_client().chat.completions.create(
        model=settings.azure_openai_chat_deployment,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
    )
    return BaselineResult(answer=response.choices[0].message.content or "", chunks=chunks)
