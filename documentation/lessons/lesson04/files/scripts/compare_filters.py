"""The Lesson 04 demonstration: the same vector query, unfiltered and filtered.

    APP_ENV=dev uv run python scripts/compare_filters.py

Look at the unfiltered scores. Five near-identical 3.4 clauses separated in the third
decimal place: the ranking between editions is noise, and no reranker fixes noise.
"""

from __future__ import annotations

from azure.search.documents.models import VectorFilterMode, VectorizedQuery

from dti_rag.clients import openai_client, search_client
from dti_rag.config import get_settings
from dti_rag.search.schema import index_name

QUERY = "What excess applies to an escape of water claim?"
RUNS = {
    "1. pure vector, no filter": None,
    "2. edition_year eq 2024": "edition_year eq 2024",
    "3. loss date 15 March 2024": (
        "effective_from le 2024-03-15T00:00:00Z and effective_to ge 2024-03-15T00:00:00Z"
    ),
}


def main() -> None:
    settings = get_settings()
    vector = (
        openai_client()
        .embeddings.create(model=settings.azure_openai_embed_deployment, input=QUERY)
        .data[0]
        .embedding
    )
    client = search_client(index_name(settings))
    print(f"app_env={settings.app_env}  query={QUERY!r}\n")
    for label, odata in RUNS.items():
        results = client.search(
            search_text=None,  # pure vector: no BM25 yet (hybrid is Lesson 06)
            vector_queries=[
                VectorizedQuery(vector=vector, k_nearest_neighbors=8, fields="contentVector")
            ],
            filter=odata,
            vector_filter_mode=VectorFilterMode.PRE_FILTER,
            select=["doc_id", "section_id", "section_title"],
            top=8,
        )
        print(label)
        for r in results:
            score, doc, section = r["@search.score"], r["doc_id"], r["section_id"]
            print(f"  {score:.4f}  {doc:24} §{section:5} {r['section_title']}")
        print()


if __name__ == "__main__":
    main()
