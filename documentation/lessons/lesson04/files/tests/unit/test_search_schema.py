"""The index schema is code: test it like code, offline."""

from __future__ import annotations

import json
from datetime import date

from dti_rag.config import Settings
from dti_rag.constants import EMBED_DIMENSIONS
from dti_rag.models import Chunk, ChunkKind, ChunkMetadata, Status
from dti_rag.search.documents import orphan_ids, to_search_document
from dti_rag.search.manifest import is_current
from dti_rag.search.schema import INDEX_NAME, SCHEMA_VERSION, build_index, index_name

SETTINGS = Settings(
    app_env="dev",
    azure_openai_endpoint="https://ai-dti-rag-dev-abcd.openai.azure.com/",
    azure_openai_api_version="2024-10-21",
    azure_openai_chat_deployment="chat",
    azure_openai_embed_deployment="embed",
    azure_search_endpoint="https://srch-dti-rag-dev-abcd.search.windows.net",
    azure_search_api_version="2024-07-01",
)

CHUNK = Chunk(
    id="DTI-HOME-PW-2024-v1_0__3_4",
    content="The standard excess for an escape of water claim is £300.",
    metadata=ChunkMetadata(
        doc_id="DTI-HOME-PW-2024-v1.0",
        edition_year=2024,
        version="1.0",
        status=Status.SUPERSEDED,
        effective_from=date(2024, 1, 1),
        effective_to=date(2024, 12, 31),
        supersedes="DTI-HOME-PW-2023-v1.1",
        superseded_by="DTI-HOME-PW-2025-v1.0",
        section_id="3.4",
        section_group="3",
        section_title="Escape of water and escape of fuel › Excess",
        chunk_kind=ChunkKind.CLAUSE,
        page=5,
    ),
)


def fields():
    return {f.name: f for f in build_index(SETTINGS).fields}


def test_index_name_is_versioned_in_code_not_config():
    assert INDEX_NAME == f"dti-policy-v{SCHEMA_VERSION}"
    assert index_name(SETTINGS) == INDEX_NAME
    assert (
        index_name(SETTINGS.model_copy(update={"azure_search_index_override": "dti-policy-pr-7"}))
        == "dti-policy-pr-7"
    )


def test_vector_field_matches_the_embedding_deployment():
    assert fields()["contentVector"].vector_search_dimensions == EMBED_DIMENSIONS


def test_dates_are_dates_not_strings():
    for name in ("effective_from", "effective_to"):
        assert fields()[name].type == "Edm.DateTimeOffset"
        assert fields()[name].filterable


def test_everything_the_retriever_filters_on_is_filterable():
    for name in (
        "doc_id",
        "edition_year",
        "version",
        "status",
        "section_id",
        "section_group",
        "chunk_kind",
    ):
        assert fields()[name].filterable, name


def test_semantic_configuration_uses_section_title():
    config = build_index(SETTINGS).semantic_search.configurations[0]
    assert config.prioritized_fields.title_field.field_name == "section_title"


def test_vectorizer_points_at_this_environments_embed_deployment():
    vectorizer = build_index(SETTINGS).vector_search.vectorizers[0]
    assert vectorizer.parameters.deployment_name == "embed"
    assert "dev" in vectorizer.parameters.resource_url


def test_document_dates_are_iso_8601_with_offset():
    doc = to_search_document(CHUNK, [0.0] * EMBED_DIMENSIONS)
    assert doc["effective_from"] == "2024-01-01T00:00:00Z"
    assert doc["effective_to"] == "2024-12-31T00:00:00Z"
    assert doc["status"] == "SUPERSEDED"
    assert json.loads(doc["metadata_json"])["section_id"] == "3.4"


def test_orphans_are_what_the_artifact_no_longer_contains():
    assert orphan_ids({"a", "b", "old"}, {"a", "b", "new"}) == {"old"}


def test_manifest_match_needs_same_corpus_schema_and_model():
    expected = {
        "schema_version": 1,
        "chunks_sha256": "abc",
        "embed_model": "m",
        "embed_model_version": "1",
    }
    assert is_current(dict(expected), expected)
    assert not is_current(None, expected)
    assert not is_current({**expected, "chunks_sha256": "def"}, expected)
    assert not is_current({**expected, "embed_model_version": "2"}, expected)
