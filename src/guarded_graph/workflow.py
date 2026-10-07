import re
from typing import TypedDict

from langchain_core.documents import Document
from langchain_core.runnables import Runnable, RunnableLambda
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from .models import Principal
from .retrieval import LocalCorpus


class GraphState(TypedDict, total=False):
    principal: Principal
    tenant_id: str
    query: str
    status: str
    evidence: tuple[Document, ...]
    answer: str


def _render_sample_answer(documents: tuple[Document, ...]) -> str:
    return "\n".join(
        f"{document.page_content} [{document.metadata['source_id']}]"
        for document in documents
    )


def build_graph(
    corpus: LocalCorpus,
    responder: Runnable[tuple[Document, ...], str] | None = None,
):
    """Compile a graph that gates access before retrieval and response."""

    response_step = responder or RunnableLambda(_render_sample_answer)

    def validate(state: GraphState) -> GraphState:
        principal = state.get("principal")
        tenant_id = state.get("tenant_id")
        query = state.get("query")
        if (
            not isinstance(principal, Principal)
            or not isinstance(tenant_id, str)
            or not re.fullmatch(r"tenant-[a-z0-9-]{1,30}", tenant_id)
            or not isinstance(query, str)
            or not query.strip()
            or len(query) > 160
            or any(ord(char) < 32 for char in query)
        ):
            return {"status": "invalid_request"}
        return {"status": "valid", "query": query.strip()}

    def authorize(state: GraphState) -> GraphState:
        tenant_id = state["tenant_id"]
        principal = state["principal"]
        if tenant_id not in principal.tenant_ids or not corpus.has_tenant(tenant_id):
            return {"status": "denied"}
        return {"status": "authorized"}

    def retrieve(state: GraphState) -> GraphState:
        tenant_id = state["tenant_id"]
        try:
            documents = corpus.retrieve(tenant_id, state["query"], limit=3)
        except Exception:  # noqa: BLE001 - hide retrieval internals at the data boundary
            return {"status": "retrieval_error", "evidence": ()}
        evidence = tuple(
            document
            for document in documents
            if document.metadata.get("tenant_id") == tenant_id
            and document.metadata.get("published") is True
            and isinstance(document.metadata.get("source_id"), str)
        )[:3]
        if not evidence:
            return {"status": "no_context", "evidence": ()}
        return {"status": "retrieved", "evidence": evidence}

    def respond(state: GraphState) -> GraphState:
        try:
            answer = response_step.invoke(state["evidence"])
        except Exception:  # noqa: BLE001 - fail closed at the replaceable response boundary
            return {"status": "response_error", "answer": ""}
        if not isinstance(answer, str) or not answer.strip():
            return {"status": "response_error", "answer": ""}
        return {"status": "answered", "answer": answer}

    graph = StateGraph(GraphState)
    graph.add_node("validate", validate)
    graph.add_node("authorize", authorize)
    graph.add_node("retrieve", retrieve)
    graph.add_node("respond", respond)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges("validate", lambda state: "authorize" if state["status"] == "valid" else END)
    graph.add_conditional_edges("authorize", lambda state: "retrieve" if state["status"] == "authorized" else END)
    graph.add_conditional_edges("retrieve", lambda state: "respond" if state["status"] == "retrieved" else END)
    graph.add_edge("respond", END)
    return graph.compile()


def run_query(graph, principal: Principal, tenant_id: str, query: str) -> dict[str, object]:
    """Expose a small response; do not return the principal or graph state."""

    with tracing_context(enabled=False):
        state = graph.invoke({"principal": principal, "tenant_id": tenant_id, "query": query})
    if state["status"] != "answered":
        return {"status": state["status"], "answer": "", "sources": []}
    return {
        "status": "answered",
        "answer": state["answer"],
        "sources": [document.metadata["source_id"] for document in state["evidence"]],
    }
