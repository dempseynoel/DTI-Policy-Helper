"""Azure client factories. Every Azure call in the codebase gets its client from here.

Authentication is Entra ID only: ``DefaultAzureCredential`` uses ``az login`` on your laptop,
OIDC in GitHub Actions and managed identity in Azure. There are no keys anywhere.
"""

from __future__ import annotations

from functools import lru_cache

import httpx
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
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
    return DefaultAzureCredential()


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
