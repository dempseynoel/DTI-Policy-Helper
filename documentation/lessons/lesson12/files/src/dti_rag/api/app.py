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
from dti_rag.query.editions import registry

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Load once at startup, not per request: a missing setting or a missing editions file
    # fails the revision here, before any traffic reaches it.
    get_settings().require("azure_ai_services_endpoint")  # the groundedness guardrail's
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


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    trace_id = uuid.uuid4().hex
    try:
        result = pipeline.answer(request.question)
    except RejectedInput as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return to_response(result, trace_id)


def _event(name: str, data: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Server-sent events: `stage` while working, then one `answer` (after guardrails)."""
    trace_id = uuid.uuid4().hex
    events: queue.Queue[tuple[str, dict]] = queue.Queue()

    def work() -> None:
        try:
            result = pipeline.answer(
                request.question, on_stage=lambda s: events.put(("stage", {"stage": s}))
            )
            events.put(("answer", to_response(result, trace_id).model_dump(mode="json")))
        except RejectedInput as exc:
            events.put(("error", {"detail": str(exc), "status": 422}))
        except Exception:  # noqa: BLE001 - the client gets a trace_id, the log gets the rest
            events.put(("error", {"detail": "internal error", "trace_id": trace_id, "status": 500}))

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
