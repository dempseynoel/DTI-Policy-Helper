"""The graph's shape, offline. Its behaviour is scored by the eval harness like the SDK path."""

import pytest

pytest.importorskip("langgraph")

from dti_rag.orchestration.graph import after_route, build_graph  # noqa: E402
from dti_rag.query.editions import load_registry  # noqa: E402
from dti_rag.query.router import Mode, Route  # noqa: E402

REG = load_registry()


def test_graph_compiles_with_the_expected_nodes():
    nodes = set(build_graph().get_graph().nodes)
    assert {"route", "retrieve", "check_agreement", "generate", "compare"} <= nodes


def test_comparisons_take_the_compare_edge():
    two = (REG.by_doc_id("DTI-HOME-PW-2024-v1.0"), REG.by_doc_id("DTI-HOME-PW-2025-v1.0"))
    compare = Route(mode=Mode.ANSWER, editions=two, reason="", question_type="comparison")
    lookup = Route(mode=Mode.ANSWER, editions=two[:1], reason="", question_type="lookup")
    assert after_route({"route": compare}) == "compare"
    assert after_route({"route": lookup}) == "retrieve"
