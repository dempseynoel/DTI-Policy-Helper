"""The index manifest: which corpus, embedded by which model, each environment is serving.

Stored as one document per policy index in the small `dti-manifest` index, so anything that
can read the policy index (the app, the smoke test, the eval harness) can read it too.
"""

from __future__ import annotations

from azure.core.exceptions import ResourceNotFoundError

from dti_rag.clients import search_client
from dti_rag.search.schema import MANIFEST_INDEX_NAME


def read_manifest(policy_index: str) -> dict | None:
    try:
        doc = search_client(MANIFEST_INDEX_NAME).get_document(key=policy_index)
    except ResourceNotFoundError:
        return None
    return {k: v for k, v in doc.items() if not k.startswith("@")}


def is_current(manifest: dict | None, expected: dict) -> bool:
    """True when the index already holds exactly this corpus, schema and embedding model."""
    if manifest is None:
        return False
    keys = ("schema_version", "chunks_sha256", "embed_model", "embed_model_version")
    return all(manifest.get(k) == expected.get(k) for k in keys)
