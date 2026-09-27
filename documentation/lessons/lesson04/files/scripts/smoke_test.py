"""Smoke test: prove this environment's model deployments answer, with no keys anywhere.

    make smoke ENV=dev

Nothing here assumes dev. Lesson 13's pipeline runs the same script against test and prod
with the pipeline's own identity.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import TypeVar
from urllib.parse import urlparse

import openai

from dti_rag.clients import openai_client
from dti_rag.config import get_settings
from dti_rag.constants import EMBED_DIMENSIONS
from dti_rag.search.manifest import read_manifest
from dti_rag.search.schema import index_name

T = TypeVar("T")

# Straight after a role assignment, 401/403 usually means "not propagated yet".
AUTH_RETRY_SECONDS = 300
AUTH_RETRY_INTERVAL = 20


def with_auth_retry(label: str, call: Callable[[], T]) -> T:
    deadline = time.monotonic() + AUTH_RETRY_SECONDS
    while True:
        try:
            return call()
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            if time.monotonic() > deadline:
                raise
            print(f"  {label}: {exc.status_code}; waiting for role propagation...")
            time.sleep(AUTH_RETRY_INTERVAL)


def check_environment_names() -> None:
    settings = get_settings()
    hosts = {
        "Foundry / OpenAI": urlparse(settings.azure_openai_endpoint).hostname or "",
        "AI Search": urlparse(settings.azure_search_endpoint).hostname or "",
    }
    print(f"APP_ENV = {settings.app_env}")
    for label, host in hosts.items():
        print(f"  {label:17} {host}")
    wrong = [f"{label} ({host})" for label, host in hosts.items() if settings.app_env not in host]
    if wrong:
        sys.exit(f"FAIL: app_env={settings.app_env} but these endpoints don't say so: {wrong}")


def check_embedding() -> None:
    settings = get_settings()
    response = with_auth_retry(
        "embed",
        lambda: openai_client().embeddings.create(
            model=settings.azure_openai_embed_deployment,  # the deployment name, not the model
            input="The standard excess for an escape of water claim is £300.",
        ),
    )
    dims = len(response.data[0].embedding)
    print(f"embed: {dims} dimensions (model {response.model})")
    if dims != EMBED_DIMENSIONS:
        sys.exit(f"FAIL: expected {EMBED_DIMENSIONS} dimensions. Wrong deployment?")


def check_chat() -> None:
    settings = get_settings()
    response = with_auth_retry(
        "chat",
        lambda: openai_client().chat.completions.create(
            model=settings.azure_openai_chat_deployment,
            # temperature=0 is used everywhere later. If this model rejects it, find out now.
            temperature=0,
            messages=[{"role": "user", "content": "Reply with the single word: ready"}],
        ),
    )
    print(f"chat: {response.choices[0].message.content!r} (model {response.model})")


def check_index() -> None:
    """Which corpus, embedded by which model, is this environment serving? (Lesson 04)"""
    index = index_name(get_settings())
    manifest = read_manifest(index)
    if manifest is None:
        sys.exit(f"FAIL: no manifest for {index}. Load it: make index ENV={get_settings().app_env}")
    print(
        f"index: {index} holds {manifest['chunk_count']} chunks, "
        f"sha256 {manifest['chunks_sha256'][:12]}, "
        f"{manifest['embed_model']} v{manifest['embed_model_version']}, "
        f"loaded {manifest['loaded_at']}"
    )


def main() -> None:
    check_environment_names()
    check_embedding()
    check_chat()
    check_index()
    print("PASS")


if __name__ == "__main__":
    main()
