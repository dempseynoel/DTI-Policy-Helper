"""The retrieval layer rebuilt in LlamaIndex, over the EXISTING index. Plus the probes.

    APP_ENV=dev python -m dti_rag.orchestration.llamaindex_retriever

Each probe answers a FRAMEWORKS.md question with evidence rather than impressions:

1. Does MetadataFilters keep pre-filtering? (Every DTI-004 chunk must be 2024.)
2. Can it express a date *range* against Edm.DateTimeOffset?
3. Does semantic ranking survive?
"""

from __future__ import annotations

from azure.identity import get_bearer_token_provider
from llama_index.core import Settings as LlamaSettings
from llama_index.core import VectorStoreIndex
from llama_index.core.vector_stores import FilterOperator, MetadataFilter, MetadataFilters
from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
from llama_index.vector_stores.azureaisearch import (
    AzureAISearchVectorStore,
    IndexManagement,
    MetadataIndexFieldType,
)

from dti_rag.clients import COGNITIVE_SERVICES_SCOPE, credential, search_client
from dti_rag.config import get_settings
from dti_rag.constants import EMBED_DIMENSIONS
from dti_rag.search.schema import EMBED_MODEL_NAME, SEMANTIC_CONFIG, index_name

String, Int32 = MetadataIndexFieldType.STRING, MetadataIndexFieldType.INT32


def configure() -> VectorStoreIndex:
    settings = get_settings()
    # Every value passed explicitly: never let the framework read the process environment.
    LlamaSettings.embed_model = AzureOpenAIEmbedding(
        model=EMBED_MODEL_NAME,
        deployment_name=settings.azure_openai_embed_deployment,  # the deployment, not the model
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
        azure_ad_token_provider=get_bearer_token_provider(credential(), COGNITIVE_SERVICES_SCOPE),
        use_azure_ad=True,
    )
    store = AzureAISearchVectorStore(
        search_or_index_client=search_client(index_name(settings)),
        index_management=IndexManagement.NO_VALIDATION,  # never let it create or alter an index
        id_field_key="id",
        chunk_field_key="content",
        embedding_field_key="contentVector",
        metadata_string_field_key="metadata_json",  # the field this framework requires
        doc_id_field_key="doc_id",
        embedding_dimensionality=EMBED_DIMENSIONS,
        semantic_configuration_name=SEMANTIC_CONFIG,
        filterable_metadata_field_keys={
            "doc_id": ("doc_id", String),
            "edition_year": ("edition_year", Int32),
            "status": ("status", String),
            "section_group": ("section_group", String),
            "effective_from": ("effective_from", String),  # there is no date type to choose
        },
    )
    return VectorStoreIndex.from_vector_store(store)


def retrieve(index: VectorStoreIndex, question: str, doc_id: str, k: int = 8):
    retriever = index.as_retriever(
        similarity_top_k=k,
        vector_store_query_mode="semantic_hybrid",
        filters=MetadataFilters(filters=[MetadataFilter(key="doc_id", value=doc_id)]),
    )
    return retriever.retrieve(question)


def main() -> None:
    index = configure()
    question = (
        "A kitchen flooded on 15 March 2024 when a dishwasher hose burst. What excess applies?"
    )

    print("Probe 1: does MetadataFilters keep pre-filtering?")
    nodes = retrieve(index, question, "DTI-HOME-PW-2024-v1.0")
    docs = {n.node.metadata.get("doc_id") for n in nodes}
    print(f"  {len(nodes)} nodes, doc_ids={docs}")
    print("  PASS: every chunk is 2024" if docs == {"DTI-HOME-PW-2024-v1.0"} else "  FAIL: leaked")
    print("  (The store never sets vector_filter_mode; it inherits the service default.)")

    print("\nProbe 2: can it express a date range?")
    date_filter = MetadataFilters(
        filters=[
            MetadataFilter(
                key="effective_from", value="2024-03-15T00:00:00Z", operator=FilterOperator.LTE
            )
        ]
    )
    try:
        index.as_retriever(filters=date_filter, similarity_top_k=3).retrieve(question)
        print("  accepted (check what came back)")
    except Exception as exc:  # noqa: BLE001 - the error IS the finding
        print(f"  rejected: {type(exc).__name__}: {str(exc)[:160]}")
        print("  String values are quoted, so 'effective_from le '2024-...'' is a type error.")

    print("\nProbe 3: does semantic ranking survive?")
    scores = [round(n.score, 3) for n in nodes[:3]]
    print(f"  top scores {scores}")
    print("  In semantic_hybrid mode the store reports @search.reranker_score (0-4 scale);")
    print("  in hybrid mode, the RRF score. Know which one a threshold is comparing against.")


if __name__ == "__main__":
    main()
