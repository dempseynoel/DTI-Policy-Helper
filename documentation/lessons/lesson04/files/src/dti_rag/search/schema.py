"""The index definition. Identical in every environment; never edited in the portal.

Any change here that Azure AI Search can't apply in place (a new filterable attribute, a
different vector size, a changed analyzer) bumps SCHEMA_VERSION. The new index is then built
alongside the old one, and the app version that expects it is deployed afterwards. Rollback
is redeploying the previous app version, whose index still exists.
"""

from __future__ import annotations

from azure.search.documents.indexes.models import (
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    HnswAlgorithmConfiguration,
    HnswParameters,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)

from dti_rag.config import Settings
from dti_rag.constants import EMBED_DIMENSIONS

SCHEMA_VERSION = 1
INDEX_NAME = f"dti-policy-v{SCHEMA_VERSION}"
MANIFEST_INDEX_NAME = "dti-manifest"

EMBED_MODEL_NAME = "text-embedding-3-large"
SEMANTIC_CONFIG = "policy-semantic"
VECTOR_PROFILE = "hnsw-aoai"
VECTORIZER = "aoai-embed"

String = SearchFieldDataType.String
Int32 = SearchFieldDataType.Int32
DateTimeOffset = SearchFieldDataType.DateTimeOffset


def index_name(settings: Settings) -> str:
    """The versioned index. Only Lesson 13's PR gate overrides it, with a throwaway index."""
    return settings.azure_search_index_override or INDEX_NAME


def build_index(settings: Settings, name: str | None = None) -> SearchIndex:
    fields = [
        SimpleField(name="id", type=String, key=True, filterable=True),
        SearchableField(name="content", type=String, analyzer_name="en.microsoft"),
        SearchField(
            name="contentVector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=EMBED_DIMENSIONS,  # immutable: a new size is a new index
            vector_search_profile_name=VECTOR_PROFILE,
        ),
        SimpleField(name="doc_id", type=String, filterable=True, facetable=True),
        SimpleField(
            name="edition_year", type=Int32, filterable=True, facetable=True, sortable=True
        ),
        SimpleField(name="version", type=String, filterable=True),
        SimpleField(name="status", type=String, filterable=True, facetable=True),
        # Dates, not strings: range comparison on a string is silently wrong.
        SimpleField(name="effective_from", type=DateTimeOffset, filterable=True, sortable=True),
        SimpleField(name="effective_to", type=DateTimeOffset, filterable=True, sortable=True),
        SimpleField(name="supersedes", type=String),
        SimpleField(name="superseded_by", type=String),
        SimpleField(name="section_id", type=String, filterable=True),
        SimpleField(name="section_group", type=String, filterable=True),
        SearchableField(name="section_title", type=String, analyzer_name="en.microsoft"),
        SimpleField(name="chunk_kind", type=String, filterable=True),
        SimpleField(name="page", type=Int32),
        SimpleField(name="metadata_json", type=String),
    ]

    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(name="hnsw", parameters=HnswParameters(metric="cosine"))
        ],
        profiles=[
            VectorSearchProfile(
                name=VECTOR_PROFILE,
                algorithm_configuration_name="hnsw",
                vectorizer_name=VECTORIZER,
            )
        ],
        # The vectorizer embeds query text at search time, as the Search service's managed
        # identity. Only the endpoint differs between environments; the deployment name is
        # the same everywhere.
        vectorizers=[
            AzureOpenAIVectorizer(
                vectorizer_name=VECTORIZER,
                parameters=AzureOpenAIVectorizerParameters(
                    resource_url=settings.azure_openai_endpoint.rstrip("/"),
                    deployment_name=settings.azure_openai_embed_deployment,
                    model_name=EMBED_MODEL_NAME,
                ),
            )
        ],
    )

    semantic_search = SemanticSearch(
        default_configuration_name=SEMANTIC_CONFIG,
        configurations=[
            SemanticConfiguration(
                name=SEMANTIC_CONFIG,
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="section_title"),
                    content_fields=[SemanticField(field_name="content")],
                ),
            )
        ],
    )

    return SearchIndex(
        name=name or index_name(settings),
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search,
    )


def build_manifest_index() -> SearchIndex:
    """One document per policy index: what corpus, embedded by what model, it holds."""
    return SearchIndex(
        name=MANIFEST_INDEX_NAME,
        fields=[
            SimpleField(name="index_name", type=String, key=True),
            SimpleField(name="schema_version", type=Int32),
            SimpleField(name="chunks_sha256", type=String),
            SimpleField(name="chunk_count", type=Int32),
            SimpleField(name="embed_deployment", type=String),
            SimpleField(name="embed_model", type=String),
            SimpleField(name="embed_model_version", type=String),
            SimpleField(name="loaded_at", type=DateTimeOffset),
            SimpleField(name="loaded_by_git_sha", type=String),
        ],
    )
