"""retrieve(query, filters): ranked, edition-correct chunks.

Three upgrades over the baseline, each switchable so you can measure what it bought:

1. Metadata filters, applied BEFORE ranking (preFilter). The one that solves this corpus.
2. Hybrid search: BM25 + vector, fused by Reciprocal Rank Fusion.
3. Semantic ranker (L2): a cross-encoder reranks the fused candidates.

retrieve() never decides which filter to apply. That's the router's job (Lesson 07); keeping
the seam is what makes both testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from azure.search.documents.models import QueryType, VectorFilterMode, VectorizableTextQuery

from dti_rag.clients import search_client
from dti_rag.config import get_settings
from dti_rag.models import RetrievedChunk
from dti_rag.retrieval.filters import SearchFilter
from dti_rag.retrieval.results import SELECT_FIELDS, to_retrieved
from dti_rag.search.schema import SEMANTIC_CONFIG, index_name


@dataclass(frozen=True)
class RetrievalConfig:
    hybrid: bool = True
    semantic: bool = True
    k: int = 8  # chunks returned to the generator
    candidates: int = 50  # nearest neighbours fed to fusion and reranking; not the same as k


DEFAULT = RetrievalConfig()


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    filter: str | None  # the OData actually sent: logged, shown and audited
    chunks: list[RetrievedChunk]


def retrieve(
    query: str, filters: SearchFilter | None = None, config: RetrievalConfig = DEFAULT
) -> RetrievalResult:
    odata = filters.to_odata() if filters else None
    semantic = (
        {
            "query_type": QueryType.SEMANTIC,
            "semantic_configuration_name": SEMANTIC_CONFIG,
            # Fail loudly if the semantic plan is missing in this environment, rather than
            # silently returning unranked results that look like a retrieval regression.
            "semantic_error_mode": "fail",
        }
        if config.semantic
        else {}
    )
    results = search_client(index_name(get_settings())).search(
        search_text=query if config.hybrid else None,
        # The index's vectorizer embeds the query text, as the Search service's identity.
        vector_queries=[
            VectorizableTextQuery(
                text=query, k_nearest_neighbors=config.candidates, fields="contentVector"
            )
        ],
        filter=odata,
        # Explicit, even though current API versions default to it: on this corpus
        # post-filtering can return nothing for an answerable question.
        vector_filter_mode=VectorFilterMode.PRE_FILTER,
        select=SELECT_FIELDS,
        top=config.k,
        **semantic,
    )
    return RetrievalResult(query=query, filter=odata, chunks=[to_retrieved(r) for r in results])
