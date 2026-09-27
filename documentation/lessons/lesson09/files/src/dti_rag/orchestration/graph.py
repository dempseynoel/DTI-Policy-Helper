"""The pipeline as a LangGraph graph.

    APP_ENV=dev python -m dti_rag.orchestration.graph "What changed between 2024 and 2025?"

                  ┌───────┐
      START ─────►│ route │
                  └───┬───┘
          comparison? │ otherwise
         ┌────────────┴────────────┐
         ▼                         ▼
    ┌──────────┐             ┌──────────┐   signposts followed inside,
    │ compare  │             │ retrieve │   same edition only
    │ (diff)   │             └────┬─────┘
    └────┬─────┘                  ▼
         │                 ┌──────────────┐   editions agree? ask -> answer
         │                 │ check_agree  │
         │                 └──────┬───────┘
         │                        ▼
         │                 ┌──────────┐
         │                 │ generate │
         ▼                 └────┬─────┘
        END ◄───────────────────┘

The nodes call the same framework-free functions as pipeline.py. The graph adds explicit
state and conditional edges; it doesn't add behaviour. That's what makes the two stacks
comparable on the eval harness, and what let the design move into pipeline.py as plain code.
"""

from __future__ import annotations

import sys
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from dti_rag.generation.compare import compare, resolve_after_retrieval
from dti_rag.generation.generate import generate
from dti_rag.models import Answer, RetrievedChunk
from dti_rag.pipeline import PipelineResult, group_by_edition, is_comparison, retrieve_for_route
from dti_rag.query.router import Route, route
from dti_rag.retrieval.retrieve import RetrievalResult


class State(TypedDict, total=False):
    question: str
    route: Route
    retrievals: list[RetrievalResult]
    by_edition: dict[str, list[RetrievedChunk]]
    answer: Answer


def route_node(state: State) -> State:
    return {"route": route(state["question"])}


def after_route(state: State) -> str:
    return "compare" if is_comparison(state["route"]) else "retrieve"


def retrieve_node(state: State) -> State:
    retrievals = retrieve_for_route(state["question"], state["route"])
    return {"retrievals": retrievals, "by_edition": group_by_edition(state["route"], retrievals)}


def check_agreement_node(state: State) -> State:
    return {"route": resolve_after_retrieval(state["route"], state["by_edition"])}


def generate_node(state: State) -> State:
    return {"answer": generate(state["question"], state["route"], state["by_edition"])}


def compare_node(state: State) -> State:
    retrievals = retrieve_for_route(state["question"], state["route"])
    by_edition = group_by_edition(state["route"], retrievals)
    return {
        "retrievals": retrievals,
        "by_edition": by_edition,
        "answer": compare(state["question"], state["route"], by_edition),
    }


def build_graph():
    graph = StateGraph(State)
    graph.add_node("route", route_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("check_agreement", check_agreement_node)
    graph.add_node("generate", generate_node)
    graph.add_node("compare", compare_node)
    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route", after_route, {"compare": "compare", "retrieve": "retrieve"}
    )
    graph.add_edge("retrieve", "check_agreement")
    graph.add_edge("check_agreement", "generate")
    graph.add_edge("generate", END)
    graph.add_edge("compare", END)
    return graph.compile()


def answer(question: str) -> PipelineResult:
    final = build_graph().invoke({"question": question})
    return PipelineResult(
        answer=final["answer"], route=final["route"], retrievals=final["retrievals"]
    )


if __name__ == "__main__":
    result = answer(" ".join(sys.argv[1:]))
    print(result.answer.text)
