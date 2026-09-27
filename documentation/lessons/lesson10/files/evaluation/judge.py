"""LLM-judge metrics via azure-ai-evaluation, using the `judge` deployment.

The judge is a different, stronger model than `chat`: a model grading its own output is
systematically generous. Its model and version are recorded in the run metadata, because
judge drift across model updates otherwise looks like pipeline regression.

Groundedness won't catch a wrong-edition answer (it IS grounded, in the wrong chunk). That's
what edition_correct is for.
"""

from __future__ import annotations

from azure.ai.evaluation import GroundednessEvaluator, RelevanceEvaluator

from dti_rag.clients import credential
from dti_rag.config import get_settings
from evaluation.rows import RunRow


def _model_config() -> dict:
    settings = get_settings()
    (judge,) = settings.require("azure_openai_judge_deployment")
    return {
        "azure_endpoint": settings.azure_openai_endpoint,
        "azure_deployment": judge,
        "api_version": settings.azure_openai_api_version,
    }


def judge_rows(rows: list[RunRow]) -> None:
    """Fill groundedness and relevance on answer/ask rows that have context. In place."""
    config = _model_config()
    groundedness = GroundednessEvaluator(config, credential=credential())
    relevance = RelevanceEvaluator(config, credential=credential())
    for row in rows:
        if row.mode == "abstain" or not row.contexts or row.error:
            continue
        context = "\n\n".join(row.contexts)
        row.groundedness = float(
            groundedness(query=row.question, response=row.answer, context=context)["groundedness"]
        )
        row.relevance = float(relevance(query=row.question, response=row.answer)["relevance"])
