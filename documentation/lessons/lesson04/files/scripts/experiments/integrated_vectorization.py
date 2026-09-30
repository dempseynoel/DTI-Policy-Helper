"""Lesson 04, loading path 2: let Azure AI Search chunk and embed the PDFs itself.

    APP_ENV=dev uv run python scripts/experiments/integrated_vectorization.py          # build + run
    APP_ENV=dev uv run python scripts/experiments/integrated_vectorization.py --status # progress
    APP_ENV=dev uv run python scripts/experiments/integrated_vectorization.py --delete # clean up

A dev-only experiment: it refuses to run anywhere else, and --delete removes every object it
created, so nothing is left for test and prod to drift from. The indexer and embedding skill
run as the Search service's managed identity (Storage Blob Data Reader on the account,
Cognitive Services OpenAI User on Foundry: infra/modules/environment/roles.tf).

Compare what comes back with your section-aware index: the Text Split skill cuts by size,
so section IDs, edition metadata and the Reserved Section 8 are all lost.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from azure.search.documents.indexes import SearchIndexerClient
from azure.search.documents.indexes.models import (
    AzureOpenAIEmbeddingSkill,
    AzureOpenAIVectorizer,
    AzureOpenAIVectorizerParameters,
    HnswAlgorithmConfiguration,
    IndexingParameters,
    InputFieldMappingEntry,
    OutputFieldMappingEntry,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SearchIndexer,
    SearchIndexerDataContainer,
    SearchIndexerDataSourceConnection,
    SearchIndexerIndexProjection,
    SearchIndexerIndexProjectionSelector,
    SearchIndexerIndexProjectionsParameters,
    SearchIndexerSkillset,
    SimpleField,
    SplitSkill,
    VectorSearch,
    VectorSearchProfile,
)
from azure.storage.blob import BlobServiceClient

from dti_rag.clients import credential, search_index_client
from dti_rag.config import get_settings
from dti_rag.constants import EMBED_DIMENSIONS
from dti_rag.search.schema import EMBED_MODEL_NAME

NAME = "dti-iv-experiment"  # data source, skillset, index and indexer all share it
CONTAINER = "corpus"
PDF_DIR = Path(__file__).resolve().parents[2] / "data" / "policy_documents"


def upload_pdfs(account: str) -> None:
    blobs = BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=credential())
    container = blobs.get_container_client(CONTAINER)
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        container.upload_blob(pdf.name, pdf.read_bytes(), overwrite=True)
        print(f"  uploaded {pdf.name}")


def build(settings) -> None:
    subscription, group, account = settings.require(
        "azure_subscription_id", "azure_resource_group", "azure_storage_account"
    )
    upload_pdfs(account)
    endpoint = settings.azure_openai_endpoint.rstrip("/")
    indexer_client = SearchIndexerClient(
        settings.azure_search_endpoint, credential(), api_version=settings.azure_search_api_version
    )

    # Storage keys are off, so the connection string is the managed-identity form.
    indexer_client.create_or_update_data_source_connection(
        SearchIndexerDataSourceConnection(
            name=NAME,
            type="azureblob",
            connection_string=(
                f"ResourceId=/subscriptions/{subscription}/resourceGroups/{group}"
                f"/providers/Microsoft.Storage/storageAccounts/{account};"
            ),
            container=SearchIndexerDataContainer(name=CONTAINER),
        )
    )

    search_index_client().create_or_update_index(
        SearchIndex(
            name=NAME,
            fields=[
                SearchField(
                    name="chunk_id",
                    type=SearchFieldDataType.String,
                    key=True,
                    analyzer_name="keyword",
                ),
                SimpleField(name="parent_id", type=SearchFieldDataType.String, filterable=True),
                SearchableField(name="title", type=SearchFieldDataType.String),
                SearchableField(name="content", type=SearchFieldDataType.String),
                SearchField(
                    name="contentVector",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    vector_search_dimensions=EMBED_DIMENSIONS,
                    vector_search_profile_name="p",
                ),
            ],
            vector_search=VectorSearch(
                algorithms=[HnswAlgorithmConfiguration(name="h")],
                profiles=[
                    VectorSearchProfile(
                        name="p", algorithm_configuration_name="h", vectorizer_name="v"
                    )
                ],
                vectorizers=[
                    AzureOpenAIVectorizer(
                        vectorizer_name="v",
                        parameters=AzureOpenAIVectorizerParameters(
                            resource_url=endpoint,
                            deployment_name=settings.azure_openai_embed_deployment,
                            model_name=EMBED_MODEL_NAME,
                        ),
                    )
                ],
            ),
        )
    )

    indexer_client.create_or_update_skillset(
        SearchIndexerSkillset(
            name=NAME,
            skills=[
                SplitSkill(
                    context="/document",
                    text_split_mode="pages",
                    maximum_page_length=2000,
                    page_overlap_length=200,
                    inputs=[InputFieldMappingEntry(name="text", source="/document/content")],
                    outputs=[OutputFieldMappingEntry(name="textItems", target_name="pages")],
                ),
                AzureOpenAIEmbeddingSkill(
                    context="/document/pages/*",
                    resource_url=endpoint,
                    deployment_name=settings.azure_openai_embed_deployment,
                    model_name=EMBED_MODEL_NAME,
                    dimensions=EMBED_DIMENSIONS,
                    inputs=[InputFieldMappingEntry(name="text", source="/document/pages/*")],
                    outputs=[OutputFieldMappingEntry(name="embedding", target_name="vector")],
                ),
            ],
            index_projection=SearchIndexerIndexProjection(
                selectors=[
                    SearchIndexerIndexProjectionSelector(
                        target_index_name=NAME,
                        parent_key_field_name="parent_id",
                        source_context="/document/pages/*",
                        mappings=[
                            InputFieldMappingEntry(name="content", source="/document/pages/*"),
                            InputFieldMappingEntry(
                                name="contentVector", source="/document/pages/*/vector"
                            ),
                            InputFieldMappingEntry(
                                name="title", source="/document/metadata_storage_name"
                            ),
                        ],
                    )
                ],
                parameters=SearchIndexerIndexProjectionsParameters(
                    projection_mode="skipIndexingParentDocuments"
                ),
            ),
        )
    )

    indexer_client.create_or_update_indexer(
        SearchIndexer(
            name=NAME,
            data_source_name=NAME,
            target_index_name=NAME,
            skillset_name=NAME,
            parameters=IndexingParameters(configuration={"dataToExtract": "contentAndMetadata"}),
        )
    )
    indexer_client.run_indexer(NAME)
    print(f"indexer {NAME} started; check progress with --status")


def status(settings) -> None:
    client = SearchIndexerClient(
        settings.azure_search_endpoint, credential(), api_version=settings.azure_search_api_version
    )
    result = client.get_indexer_status(NAME).last_result
    if result is None:
        print("not run yet")
        return
    print(f"{result.status}: {result.item_count} items, {result.failed_item_count} failed")
    for error in result.errors or []:
        print(f"  error: {error.error_message}")


def delete(settings) -> None:
    client = SearchIndexerClient(
        settings.azure_search_endpoint, credential(), api_version=settings.azure_search_api_version
    )
    client.delete_indexer(NAME)
    client.delete_skillset(NAME)
    client.delete_data_source_connection(NAME)
    search_index_client().delete_index(NAME)
    print(f"deleted indexer, skillset, data source and index {NAME}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true")
    group.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if settings.app_env != "dev":  # guarding an experiment is what app_env is for
        sys.exit("This experiment runs in dev only.")
    if args.status:
        status(settings)
    elif args.delete:
        delete(settings)
    else:
        build(settings)


if __name__ == "__main__":
    main()
