"""Run every output guardrail and decide what the handler sees."""

from __future__ import annotations

from dti_rag.guardrails.figures import check_figures
from dti_rag.guardrails.groundedness import detect
from dti_rag.models import Answer, RetrievedChunk

BLOCKED_TEXT = (
    "I can't give a reliable answer to this. My draft contained a figure that isn't in the "
    "policy wording I retrieved, so it has been withheld. Please check the cited clauses "
    "directly, or rephrase the question."
)


def apply_guardrails(
    question: str, answer: Answer, chunks: list[RetrievedChunk]
) -> tuple[Answer, str]:
    """Return the answer the handler sees, and the draft text (kept for the audit log)."""
    draft = answer.text
    figures = check_figures(draft, question, chunks, answer.calculations)
    status = figures.status
    detail = figures.reasons()

    if status != "blocked" and answer.mode != "abstain" and chunks:
        grounded = detect(question, draft, [c.content for c in chunks])
        detail.append(f"groundedness: {grounded.status} {grounded.detail}".strip())
        if grounded.status == "ungrounded" and status == "passed":
            status = "flagged"

    shown = answer.model_copy(
        update={
            "text": BLOCKED_TEXT if status == "blocked" else draft,
            "guardrail_status": status,
            "guardrail_detail": detail,
        }
    )
    return shown, draft
