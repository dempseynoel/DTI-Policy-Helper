"""Azure client factories. Every Azure call in the codebase gets its client from here.

Authentication is Entra ID only: ``DefaultAzureCredential`` uses ``az login`` on your laptop,
OIDC in GitHub Actions and managed identity in Azure. There are no keys anywhere.
"""

from __future__ import annotations

from functools import lru_cache

import httpx
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from openai import AzureOpenAI

from dti_rag.config import get_settings

COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"

_throttled_responses = 0


def _count_throttling(response: httpx.Response) -> None:
    global _throttled_responses
    if response.status_code == 429:
        _throttled_responses += 1


def throttled_response_count() -> int:
    """How many 429s the OpenAI client has received (and retried) in this process.

    The eval harness records this in every scorecard: throttling is a result, not noise.
    """
    return _throttled_responses


@lru_cache(maxsize=1)
def credential() -> DefaultAzureCredential:
    # In Azure: the app's user-assigned identity (Lesson 12). On your laptop and in GitHub
    # Actions no managed identity is available, so the chain falls through to az login.
    client_id = get_settings().app_identity_client_id
    return DefaultAzureCredential(managed_identity_client_id=client_id)


@lru_cache(maxsize=1)
def openai_client() -> AzureOpenAI:
    settings = get_settings()
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
        # A token *provider* (a callable), not a token string. A string works for an hour
        # and then expires in a way that is confusing to debug.
        azure_ad_token_provider=get_bearer_token_provider(credential(), COGNITIVE_SERVICES_SCOPE),
        max_retries=5,
        http_client=httpx.Client(timeout=60, event_hooks={"response": [_count_throttling]}),
    )


def search_client(index: str) -> SearchClient:
    settings = get_settings()
    return SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=index,
        credential=credential(),
        api_version=settings.azure_search_api_version,  # pinned, identical everywhere
    )


@lru_cache(maxsize=1)
def search_index_client() -> SearchIndexClient:
    settings = get_settings()
    return SearchIndexClient(
        endpoint=settings.azure_search_endpoint,
        credential=credential(),
        api_version=settings.azure_search_api_version,
    )
