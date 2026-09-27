"""FastAPI app: POST /chat, POST /chat/stream, GET /editions, GET /health, and the UI.

    make run ENV=dev          then open http://localhost:8000

Streaming shows progress, but the answer is BUFFERED until the guardrails have run. The
alternative (stream text, then retract it) means a handler can act on a figure that was
withdrawn a second later.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from dti_rag import pipeline
from dti_rag.api.schemas import ChatRequest, ChatResponse, EditionOut
from dti_rag.config import get_settings
from dti_rag.guardrails.user_input import RejectedInput
from dti_rag.observability import audit
from dti_rag.observability.telemetry import configure_telemetry, current_trace_id, span
from dti_rag.query.editions import registry

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Load once at startup, not per request: a missing setting or a missing editions file
    # fails the revision here, before any traffic reaches it.
    get_settings().require("azure_ai_services_endpoint", "azure_storage_account")
    configure_telemetry()
    registry()
    yield


app = FastAPI(title="DTI Policy Helper", lifespan=lifespan)


def to_response(result: pipeline.PipelineResult, trace_id: str) -> ChatResponse:
    a = result.answer
    return ChatResponse(
        answer=a.text,
        mode=a.mode,
        citations=a.citations,
        governing_editions=a.governing_editions,
        edition_reason=a.edition_reason,
        guardrail_status=a.guardrail_status,
        guardrail_detail=a.guardrail_detail,
        trace_id=trace_id,
        prompt_version=a.prompt_version,
        git_sha=get_settings().git_sha or "local",
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness and readiness. Never calls a model: a probe that burns tokens costs money
    every time the app scales."""
    return {"status": "ok", "app_env": get_settings().app_env}


@app.get("/editions", response_model=list[EditionOut])
def editions() -> list[EditionOut]:
    return [
        EditionOut(
            doc_id=e.doc_id,
            edition_year=e.edition_year,
            version=e.version,
            status=e.status.value,
            effective_from=e.effective_from.isoformat(),
            effective_to=e.effective_to.isoformat(),
        )
        for e in registry().editions
    ]


class AuditUnavailable(RuntimeError):
    pass


def answer_and_audit(question: str, on_stage=None) -> ChatResponse:
    """Run the pipeline inside one trace, write the audit record, then return the answer.

    Fail closed: if the audit record can't be written, the answer isn't returned.
    """
    with span("chat") as s:
        trace_id = current_trace_id() or uuid.uuid4().hex
        s.set_attribute("dti.trace_id", trace_id)
        result = pipeline.answer(question, on_stage=on_stage)
        try:
            audit.write_record(audit.build_record(result, question, trace_id))
        except Exception as exc:
            raise AuditUnavailable(trace_id) from exc
        return to_response(result, trace_id)


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    try:
        return answer_and_audit(request.question)
    except RejectedInput as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AuditUnavailable as exc:
        raise HTTPException(
            status_code=503, detail=f"couldn't record the audit trail; try again (trace {exc})"
        ) from exc


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Server-sent events: `stage` while working, then one `answer` (after guardrails)."""
    events: queue.Queue[tuple[str, dict]] = queue.Queue()

    def work() -> None:
        try:
            response = answer_and_audit(
                request.question, on_stage=lambda s: events.put(("stage", {"stage": s}))
            )
            events.put(("answer", response.model_dump(mode="json")))
        except RejectedInput as exc:
            events.put(("error", {"detail": str(exc), "status": 422}))
        except AuditUnavailable as exc:
            events.put(
                (
                    "error",
                    {
                        "detail": "couldn't record the audit trail; try again",
                        "trace_id": str(exc),
                        "status": 503,
                    },
                )
            )
        except Exception:  # noqa: BLE001 - the client gets a status, the trace gets the rest
            events.put(("error", {"detail": "internal error", "status": 500}))

    async def stream() -> AsyncIterator[str]:
        threading.Thread(target=work, daemon=True).start()
        while True:
            try:
                name, data = events.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
            yield _event(name, data)
            if name in ("answer", "error"):
                return

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/")
def ui() -> FileResponse:
    return FileResponse(STATIC / "index.html")
