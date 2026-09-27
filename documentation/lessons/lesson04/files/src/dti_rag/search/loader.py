"""Load artifacts/chunks.jsonl into this environment's index (the push model).

    make index ENV=dev

The same loader runs in every environment: you run it in dev, the pipeline runs it in test
and prod (Lesson 13) as that environment's deploy identity. It:

1. creates or updates the index and the manifest index from code;
2. skips everything else if the manifest says this exact corpus and model are already loaded;
3. embeds in batches with this environment's own `embed` deployment (vectors are never
   copied between environments);
4. uploads with mergeOrUpload and fails loudly on any per-document failure;
5. deletes documents the artefact no longer contains;
6. writes the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from dti_rag.clients import openai_client, search_client, search_index_client
from dti_rag.config import get_settings
from dti_rag.models import Chunk
from dti_rag.runinfo import serving_models
from dti_rag.search.documents import orphan_ids, read_chunks, to_search_document
from dti_rag.search.manifest import is_current, read_manifest
from dti_rag.search.schema import (
    EMBED_MODEL_NAME,
    MANIFEST_INDEX_NAME,
    SCHEMA_VERSION,
    build_index,
    build_manifest_index,
    index_name,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CHUNKS = ROOT / "artifacts" / "chunks.jsonl"
EMBED_BATCH = 16
UPLOAD_BATCH = 500  # well under the 1000-document / 16 MB request limit


def embed_all(chunks: list[Chunk]) -> list[list[float]]:
    settings = get_settings()
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        response = openai_client().embeddings.create(
            model=settings.azure_openai_embed_deployment, input=[c.content for c in batch]
        )
        vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        print(f"  embedded {len(vectors)}/{len(chunks)}")
    return vectors


def upload(index: str, documents: list[dict]) -> None:
    client = search_client(index)
    for start in range(0, len(documents), UPLOAD_BATCH):
        results = client.merge_or_upload_documents(documents[start : start + UPLOAD_BATCH])
        # Partial failure is normal and the call doesn't raise. Check every result.
        failed = [(r.key, r.error_message) for r in results if not r.succeeded]
        if failed:
            raise RuntimeError(f"{len(failed)} documents failed to upload: {failed[:5]}")


def delete_orphans(index: str, keep: set[str]) -> int:
    client = search_client(index)
    indexed = {d["id"] for d in client.search(search_text="*", select=["id"], top=10_000)}
    orphans = orphan_ids(indexed, keep)
    if orphans:
        results = client.delete_documents([{"id": key} for key in sorted(orphans)])
        failed = [r.key for r in results if not r.succeeded]
        if failed:
            raise RuntimeError(f"failed to delete orphans: {failed}")
    return len(orphans)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS)
    parser.add_argument("--force", action="store_true", help="reload even if the manifest matches")
    args = parser.parse_args()

    settings = get_settings()  # refuses to run without APP_ENV
    index = index_name(settings)
    data = args.chunks.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    chunks = read_chunks(args.chunks)

    embed = serving_models(settings)[settings.azure_openai_embed_deployment]
    if embed.model != EMBED_MODEL_NAME:
        raise RuntimeError(f"`{embed.deployment}` serves {embed.model}, not {EMBED_MODEL_NAME}")
    expected = {
        "index_name": index,
        "schema_version": SCHEMA_VERSION,
        "chunks_sha256": sha,
        "chunk_count": len(chunks),
        "embed_deployment": embed.deployment,
        "embed_model": embed.model,
        "embed_model_version": embed.version,
    }
    print(f"app_env={settings.app_env} index={index} chunks={len(chunks)} sha256={sha[:12]}")

    indexes = search_index_client()
    indexes.create_or_update_index(build_index(settings, index))
    indexes.create_or_update_index(build_manifest_index())

    if not args.force and is_current(read_manifest(index), expected):
        print("manifest matches: index already holds this corpus and model. Nothing to do.")
        return

    vectors = embed_all(chunks)
    upload(index, [to_search_document(c, v) for c, v in zip(chunks, vectors, strict=True)])
    deleted = delete_orphans(index, {c.id for c in chunks})

    manifest = {
        **expected,
        "loaded_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "loaded_by_git_sha": settings.git_sha or "local",
    }
    upload(MANIFEST_INDEX_NAME, [manifest])
    print(f"loaded {len(chunks)} chunks, deleted {deleted} orphans, manifest written")


if __name__ == "__main__":
    main()
