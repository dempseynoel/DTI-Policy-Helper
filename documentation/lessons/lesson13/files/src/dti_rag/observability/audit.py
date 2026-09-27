"""The audit trail: for every answer, enough to reconstruct it months later.

Asked in six months why a customer was told £300: this question, this edition, this reason,
these chunks, this draft, this answer, this prompt version, this code, this environment.

- Complete: never sampled. One JSON blob per answer, `audit/<trace_id>.json`, in this
  environment's storage account. Retention by a lifecycle rule
  (infra/modules/environment/storage.tf).
- Redacted: the question, draft and answer go through pii.redact() first. Policy wording
  isn't personal data and is kept verbatim.
- Read back by trace_id: Lesson 13's promotion gate reads context from here, so every
  promotion also proves the audit trail works.
- Fail closed: if the record can't be written, the API doesn't return the answer
  (api/app.py). An answer that can't be audited isn't given.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from dti_rag.clients import credential
from dti_rag.config import get_settings
from dti_rag.guardrails.pii import redact

AUDIT_CONTAINER = "audit"


def build_record(result: Any, question: str, trace_id: str) -> dict[str, Any]:
    """Pure: PipelineResult -> the audit record. Unit-tested offline."""
    settings = get_settings()
    route = result.route
    a = result.answer
    return {
        "trace_id": trace_id,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "app_env": settings.app_env,
        "git_sha": settings.git_sha or "local",
        "prompt_version": a.prompt_version,
        "deployments": {
            "chat": settings.azure_openai_chat_deployment,
            "embed": settings.azure_openai_embed_deployment,
        },
        "question": redact(question),
        "route": {
            "mode": a.mode,
            "editions": a.governing_editions,
            "reason": a.edition_reason,
            "question_type": getattr(route, "question_type", None),
            "abstain_reason": getattr(route, "abstain_reason", None),
            "extraction": route.extraction.model_dump()
            if getattr(route, "extraction", None)
            else None,
        },
        "searches": [{"query": redact(r.query), "filter": r.filter} for r in result.retrievals],
        "chunks": [
            {"id": c.id, "doc_id": c.doc_id, "section_id": c.section_id, "content": c.content}
            for c in result.chunks
        ],
        "draft": redact(result.draft_text),
        "answer": redact(a.text),
        "citations": [c.model_dump(mode="json") for c in a.citations],
        "calculations": [c.model_dump() for c in a.calculations],
        "guardrail": {"status": a.guardrail_status, "detail": a.guardrail_detail},
        "warnings": a.warnings,
    }


@lru_cache(maxsize=1)
def _container():
    from azure.storage.blob import BlobServiceClient

    (account,) = get_settings().require("azure_storage_account")
    service = BlobServiceClient(f"https://{account}.blob.core.windows.net", credential=credential())
    return service.get_container_client(AUDIT_CONTAINER)


def write_record(record: dict[str, Any]) -> None:
    _container().upload_blob(
        f"{record['trace_id']}.json",
        json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        overwrite=False,  # an audit record is written once, never replaced
    )


def read_record(trace_id: str) -> dict[str, Any]:
    return json.loads(_container().download_blob(f"{trace_id}.json").readall())
