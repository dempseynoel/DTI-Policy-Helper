"""The API contract, offline: the pipeline is replaced with a fake."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from dti_rag import pipeline
from dti_rag.api import app as app_module
from dti_rag.config import Settings
from dti_rag.guardrails.user_input import RejectedInput
from dti_rag.models import Answer, Citation

SETTINGS = Settings(
    app_env="dev",
    azure_openai_endpoint="https://ai-dti-rag-dev-x.openai.azure.com/",
    azure_openai_api_version="2024-10-21",
    azure_openai_chat_deployment="chat",
    azure_openai_embed_deployment="embed",
    azure_search_endpoint="https://srch-dti-rag-dev-x.search.windows.net",
    azure_search_api_version="2024-07-01",
    azure_ai_services_endpoint="https://ai-dti-rag-dev-x.cognitiveservices.azure.com/",
    azure_storage_account="stdtiragdevx",
    git_sha="abc123",
)


def fake_answer(question, on_stage=None):
    if not question.strip("\x00 "):
        raise RejectedInput("the question is empty")
    for stage in ("route", "retrieve", "generate", "guardrails"):
        if on_stage:
            on_stage(stage)
    answer = Answer(
        mode="answer",
        text="£300.",
        governing_editions=["DTI-HOME-PW-2024-v1.0"],
        edition_reason="The loss date (15 March 2024) falls within the 2024 edition.",
        citations=[
            Citation(
                doc_id="DTI-HOME-PW-2024-v1.0",
                section_id="3.4",
                section_title="Excess",
                effective_from=date(2024, 1, 1),
                effective_to=date(2024, 12, 31),
                page=5,
                quoted_text="The standard excess for an escape of water claim is £300.",
            )
        ],
        prompt_version="gen-v2",
        guardrail_status="passed",
    )
    return pipeline.PipelineResult(answer=answer, route=None, retrievals=[])


@pytest.fixture
def audited(monkeypatch):
    records: list[dict] = []
    monkeypatch.setattr(
        app_module.audit, "build_record", lambda result, q, trace_id: {"trace_id": trace_id, "q": q}
    )
    monkeypatch.setattr(app_module.audit, "write_record", records.append)
    return records


@pytest.fixture
def client(monkeypatch, audited):
    monkeypatch.setattr(app_module, "get_settings", lambda: SETTINGS)
    monkeypatch.setattr(app_module, "configure_telemetry", lambda: None)
    monkeypatch.setattr(pipeline, "answer", fake_answer)
    with TestClient(app_module.app) as c:
        yield c


def test_health_never_calls_the_pipeline(client, monkeypatch):
    monkeypatch.setattr(pipeline, "answer", lambda *a, **k: pytest.fail("health called a model"))
    assert client.get("/health").json() == {"status": "ok", "app_env": "dev"}


def test_chat_returns_the_full_contract(client):
    body = client.post("/chat", json={"question": "kitchen flooded 15 March 2024"}).json()
    assert body["answer"] == "£300."
    assert body["governing_editions"] == ["DTI-HOME-PW-2024-v1.0"]
    assert "15 March 2024" in body["edition_reason"]
    assert body["citations"][0]["quoted_text"].startswith("The standard excess")
    assert body["guardrail_status"] == "passed"
    assert body["git_sha"] == "abc123"
    assert len(body["trace_id"]) == 32


def test_rejected_input_is_a_422(client):
    assert client.post("/chat", json={"question": "\x00\x00"}).status_code == 422


def test_editions_lists_all_five(client):
    assert [e["doc_id"] for e in client.get("/editions").json()][-1] == "DTI-HOME-PW-2025-v1.0"


def test_stream_sends_stages_then_one_buffered_answer(client):
    with client.stream("POST", "/chat/stream", json={"question": "excess?"}) as r:
        text = "".join(r.iter_text())
    events = [
        line.removeprefix("event: ") for line in text.splitlines() if line.startswith("event: ")
    ]
    assert events == ["stage", "stage", "stage", "stage", "answer"]


def test_ui_is_served(client):
    assert "Governing edition" in client.get("/").text


def test_every_answer_is_audited_under_its_trace_id(client, audited):
    body = client.post("/chat", json={"question": "excess?"}).json()
    assert audited == [{"trace_id": body["trace_id"], "q": "excess?"}]


def test_no_audit_record_means_no_answer(client, monkeypatch):
    def fail(record):
        raise OSError("storage unavailable")

    monkeypatch.setattr(app_module.audit, "write_record", fail)
    response = client.post("/chat", json={"question": "excess?"})
    assert response.status_code == 503
    assert "£300" not in response.text
