# Architecture

The example separates caller identity, authorization, retrieval, and response generation. All data is created in source as fictional fixtures. The CLI is an exploration interface; it is not an identity provider.

## Data flow

1. `validate` rejects malformed tenant names, blank or oversized queries, and control characters.
2. `authorize` checks principal membership before looking up the tenant. Unknown tenants and catalog failures stop before retrieval.
3. `retrieve` reads only the selected tenant's in-memory bucket, then accepts documents whose metadata matches that tenant and whose state is exactly `published=True`. A second check in the graph enforces the same boundary before response generation.
4. `respond` invokes a LangChain `Runnable` with at most three scoped `Document` objects. The default runnable renders their synthetic text with source IDs. Errors return an empty response.
5. `run_query` returns only `status`, `answer`, and `sources`; it never returns the principal or internal graph state.

The authorization edge is before retrieval. Neither a model nor a query string can select another tenant's bucket by itself. The tests assert that a denied request never calls the retrieval method or response runnable.

## Trust boundary

`Principal` is assumed to be created by trusted upstream authentication. The sample CLI chooses between two hardcoded fictional principals for demonstration. An actual API would need authenticated identity, a tenant membership source, storage-level row policies, request rate limits, audit logging, and a review of any model integration. None of those production controls are claimed here.

This graph is deliberately offline. `run_query` disables LangSmith tracing for the entire graph invocation, including the response runnable, even if tracing is configured in the surrounding process. It does not contain an LLM or authored prompt, and its deterministic response does not demonstrate answer quality. The response runnable is an integration boundary where a model could be added only after a separate design that handles untrusted document text, output validation, privacy, and cost.

## Code map

| File | Responsibility |
| --- | --- |
| `src/guarded_graph/models.py` | Trusted principal contract |
| `src/guarded_graph/retrieval.py` | Synthetic corpus and bounded lexical search |
| `src/guarded_graph/workflow.py` | LangGraph routing, authorization, and response boundary |
| `src/guarded_graph/cli.py` | Offline demonstration interface |
| `tests/test_workflow.py` | Positive, negative, isolation, and failure-path checks |
