"""Groundedness detection (Azure AI Content Safety), from this environment's Foundry resource.

A second, model-based opinion on every answer, run in production and not just in eval.
It FLAGS, never blocks: the deterministic figure check is the blocking control, and a
model-based check that blocks would turn its false positives into outages.

The API version is a preview. Check it's available in your region, and record the decision
to use a preview API in prod in GUARDRAILS.md. The app identity's Foundry User role covers
the call; the narrower Cognitive Services OpenAI User role would not.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from dti_rag.clients import COGNITIVE_SERVICES_SCOPE, credential
from dti_rag.config import get_settings

API_VERSION = "2024-09-15-preview"
MAX_SOURCES_CHARS = 50_000
TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class GroundednessResult:
    status: str  # grounded | ungrounded | unavailable
    detail: str = ""


def detect(question: str, answer: str, sources: list[str]) -> GroundednessResult:
    try:
        (endpoint,) = get_settings().require("azure_ai_services_endpoint")
        budget, kept = MAX_SOURCES_CHARS, []
        for source in sources:
            if len(source) > budget:
                break
            kept.append(source)
            budget -= len(source)
        token = credential().get_token(COGNITIVE_SERVICES_SCOPE).token
        response = httpx.post(
            f"{endpoint.rstrip('/')}/contentsafety/text:detectGroundedness",
            params={"api-version": API_VERSION},
            headers={"Authorization": f"Bearer {token}"},
            json={
                "domain": "Generic",
                "task": "QnA",
                "qna": {"query": question},
                "text": answer,
                "groundingSources": kept,
                "reasoning": False,
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()
    except Exception as exc:  # noqa: BLE001 - unavailable is recorded, never hidden
        return GroundednessResult("unavailable", f"{type(exc).__name__}: {exc}"[:200])
    if body.get("ungroundedDetected"):
        return GroundednessResult(
            "ungrounded", f"{body.get('ungroundedPercentage', 0):.0%} ungrounded"
        )
    return GroundednessResult("grounded")
