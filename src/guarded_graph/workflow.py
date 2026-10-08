import re
from typing import TypedDict

from langchain_core.documents import Document
from langchain_core.runnables import Runnable, RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langsmith import tracing_context

from .models import Principal
from .retrieval import LocalCorpus, _tokens


class GraphState(TypedDict, total=False):
    principal: Principal
    tenant_id: str
    query: str
    search_query: str
    retrieval_attempts: int
    status: str
    evidence: tuple[Document, ...]
    answer: str


def _render_sample_answer(documents: tuple[Document, ...]) -> str:
    return "\n".join(
        f"{document.page_content} [{document.metadata['source_id']}]"
        for document in documents
    )


def _singular_retry(query: str) -> str | None:
    """Offer one predictable lexical fallback for plural search terms."""

    words = re.findall(r"[a-z0-9]+", query.lower())
    normalized = [
        word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word
        for word in words
    ]
    return " ".join(normalized) if normalized != words else None


def build_graph(
    corpus: LocalCorpus,
    responder: Runnable[tuple[Document, ...], str] | None = None,
) -> CompiledStateGraph[GraphState, None, GraphState, GraphState]:
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
        clean_query = query.strip()
        return {
            "status": "valid",
            "query": clean_query,
            "search_query": clean_query,
            "retrieval_attempts": 0,
        }

    def authorize(state: GraphState) -> GraphState:
        tenant_id = state["tenant_id"]
        principal = state["principal"]
        if tenant_id not in principal.tenant_ids:
            return {"status": "denied"}
        try:
            known_tenant = corpus.has_tenant(tenant_id)
        except Exception:  # noqa: BLE001 - catalog failure must not permit retrieval
            return {"status": "authorization_error"}
        if not known_tenant:
            return {"status": "denied"}
        return {"status": "authorized"}

    def retrieve(state: GraphState) -> GraphState:
        tenant_id = state["tenant_id"]
        attempt = state["retrieval_attempts"] + 1
        try:
            documents = corpus.retrieve(tenant_id, state["search_query"], limit=3)
            evidence = tuple(
                document
                for document in documents
                if isinstance(document, Document)
                and document.metadata.get("tenant_id") == tenant_id
                and document.metadata.get("published") is True
                and isinstance(document.metadata.get("source_id"), str)
                and document.metadata["source_id"]
            )[:3]
        except Exception:  # noqa: BLE001 - hide retrieval internals at the data boundary
            return {"status": "retrieval_error", "evidence": (), "retrieval_attempts": attempt}
        return {"status": "retrieved", "evidence": evidence, "retrieval_attempts": attempt}

    def evaluate(state: GraphState) -> GraphState:
        terms = _tokens(state["search_query"])
        relevant = tuple(
            document for document in state["evidence"] if terms & _tokens(document.page_content)
        )
        if relevant:
            return {"status": "ready", "evidence": relevant}
        if state["retrieval_attempts"] < 2:
            retry_query = _singular_retry(state["query"])
            if retry_query is not None and retry_query != state["search_query"]:
                return {"status": "retry", "search_query": retry_query, "evidence": ()}
        return {"status": "no_context", "evidence": ()}

    def respond(state: GraphState) -> GraphState:
        try:
            answer = response_step.invoke(state["evidence"])
        except Exception:  # noqa: BLE001 - fail closed at the replaceable response boundary
            return {"status": "response_error", "answer": ""}
        if not isinstance(answer, str) or not answer.strip():
            return {"status": "response_error", "answer": ""}
        return {"status": "answered", "answer": answer}

    def after_evaluate(state: GraphState) -> str:
        if state["status"] == "ready":
            return "respond"
        if state["status"] == "retry":
            return "retrieve"
        return END

    graph = StateGraph(GraphState)
    graph.add_node("validate", validate)
    graph.add_node("authorize", authorize)
    graph.add_node("retrieve", retrieve)
    graph.add_node("evaluate", evaluate)
    graph.add_node("respond", respond)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges("validate", lambda state: "authorize" if state["status"] == "valid" else END)
    graph.add_conditional_edges("authorize", lambda state: "retrieve" if state["status"] == "authorized" else END)
    graph.add_conditional_edges("retrieve", lambda state: "evaluate" if state["status"] == "retrieved" else END)
    graph.add_conditional_edges("evaluate", after_evaluate)
    graph.add_edge("respond", END)
    return graph.compile()


def run_query(
    graph: CompiledStateGraph[GraphState, None, GraphState, GraphState],
    principal: Principal,
    tenant_id: str,
    query: str,
) -> dict[str, object]:
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
