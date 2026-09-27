from datetime import date

import pytest

from dti_rag.config import Settings
from dti_rag.models import Answer, ChunkKind, RetrievedChunk
from dti_rag.observability.audit import build_record
from dti_rag.pipeline import PipelineResult
from dti_rag.query.editions import load_registry
from dti_rag.query.router import Mode, Route
from dti_rag.retrieval.retrieve import RetrievalResult

SETTINGS = Settings(
    app_env="dev",
    azure_openai_endpoint="https://ai-dti-rag-dev-x.openai.azure.com/",
    azure_openai_api_version="2024-10-21",
    azure_openai_chat_deployment="chat",
    azure_openai_embed_deployment="embed",
    azure_search_endpoint="https://srch-dti-rag-dev-x.search.windows.net",
    azure_search_api_version="2024-07-01",
    git_sha="abc123",
)

REG = load_registry()


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setattr("dti_rag.observability.audit.get_settings", lambda: SETTINGS)


def result() -> PipelineResult:
    chunk = RetrievedChunk(
        id="DTI-HOME-PW-2024-v1_0__3_4",
        content="The standard excess for an escape of water claim is £300.",
        doc_id="DTI-HOME-PW-2024-v1.0",
        edition_year=2024,
        version="1.0",
        effective_from=date(2024, 1, 1),
        effective_to=date(2024, 12, 31),
        section_id="3.4",
        section_group="3",
        section_title="Excess",
        chunk_kind=ChunkKind.CLAUSE,
        page=5,
    )
    answer = Answer(
        mode="answer",
        text="£300. Contact jane@example.com for details.",
        governing_editions=["DTI-HOME-PW-2024-v1.0"],
        edition_reason="loss date",
        citations=[],
        prompt_version="gen-v2",
        guardrail_status="passed",
    )
    route = Route(
        mode=Mode.ANSWER, editions=(REG.by_doc_id("DTI-HOME-PW-2024-v1.0"),), reason="loss date"
    )
    return PipelineResult(
        answer=answer,
        route=route,
        retrievals=[
            RetrievalResult(query="q", filter="doc_id eq 'DTI-HOME-PW-2024-v1.0'", chunks=[chunk])
        ],
        draft_text="£300. Contact jane@example.com for details.",
    )


def test_record_reconstructs_the_answer():
    record = build_record(result(), "Flood on 15 March 2024, customer at DV1 2AA", "t" * 32)
    assert record["trace_id"] == "t" * 32
    assert record["app_env"] == "dev" and record["git_sha"] == "abc123"
    assert record["prompt_version"] == "gen-v2"
    assert record["route"]["editions"] == ["DTI-HOME-PW-2024-v1.0"]
    assert record["searches"][0]["filter"] == "doc_id eq 'DTI-HOME-PW-2024-v1.0'"
    assert "£300" in record["chunks"][0]["content"]  # policy wording kept verbatim


def test_personal_data_is_redacted_before_it_is_recorded():
    record = build_record(result(), "Flood on 15 March 2024, customer at DV1 2AA", "t" * 32)
    assert "DV1 2AA" not in record["question"] and "[POSTCODE]" in record["question"]
    assert "jane@example.com" not in record["answer"]
    assert "jane@example.com" not in record["draft"]


def test_token_usage_accumulates_across_calls_in_one_span():
    from types import SimpleNamespace

    from opentelemetry.sdk.trace import TracerProvider

    from dti_rag.observability.telemetry import record_usage

    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("generate") as span:
        record_usage(SimpleNamespace(prompt_tokens=100, completion_tokens=10))
        record_usage(SimpleNamespace(prompt_tokens=50, completion_tokens=5))
        assert span.attributes["gen_ai.usage.input_tokens"] == 150
        assert span.attributes["gen_ai.usage.output_tokens"] == 15


def test_the_telemetry_distro_imports():
    """The app imports this at startup. A resolver can pair an old distro with an
    opentelemetry-sdk it doesn't support; the unit tests would never notice otherwise."""
    from azure.monitor.opentelemetry import configure_azure_monitor

    assert callable(configure_azure_monitor)
