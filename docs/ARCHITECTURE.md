# Architecture

The example separates caller identity, authorization, retrieval, and response generation. All data is created in source as fictional fixtures. The CLI is an exploration interface; it is not an identity provider.

## Data flow

1. `validate` rejects malformed tenant names, blank or oversized queries, and control characters.
2. `authorize` checks principal membership before looking up the tenant. Unknown tenants and catalog failures stop before retrieval.
3. `retrieve` reads only the selected tenant's in-memory bucket, then accepts documents whose metadata matches that tenant and whose state is exactly `published=True`. The graph checks this boundary on every attempt, including the retry. A retrieval failure stops with an empty response.
4. `evaluate` retains only documents with lexical overlap against the active search query. If there is no relevant evidence on the first attempt, a deterministic fallback removes one trailing `s` from eligible terms and routes back to `retrieve` once. `retrieval_attempts` and `search_query` are explicit graph state. A second miss, an ineligible query, or a read error ends without an answer.
5. `respond` invokes a LangChain `Runnable` with at most three scoped, lexically matched `Document` objects. The default runnable renders their synthetic text with source IDs. Errors return an empty response and do not trigger another read.
6. `run_query` returns only `status`, `answer`, and `sources`; it never returns the principal or internal graph state.

The authorization edge is before every retrieval path. The retry can change the search terms but never the tenant ID or principal. Neither a model nor a query string can select another tenant's bucket by itself. Tests assert that denied requests never read the catalog or documents, that a retry is capped at two reads, and that misfiled documents never reach the responder.

## Trust boundary

`Principal` is assumed to be created by trusted upstream authentication. The sample CLI chooses between two hardcoded fictional principals for demonstration. An actual API would need authenticated identity, a tenant membership source, storage-level row policies, request rate limits, audit logging, and a review of any model integration. None of those production controls are claimed here.

This graph is deliberately offline. `run_query` disables LangSmith tracing for the entire graph invocation, including the response runnable, even if tracing is configured in the surrounding process. It does not contain an LLM or authored prompt. Lexical overlap and singularization can miss relevant material or accept a misleading match; neither demonstrates answer quality. The response runnable is an integration boundary where a model could be added only after a separate design that handles untrusted document text, output validation, privacy, and cost.

## Code map

| File | Responsibility |
| --- | --- |
| `src/guarded_graph/models.py` | Trusted principal contract |
| `src/guarded_graph/retrieval.py` | Synthetic corpus and bounded lexical search |
| `src/guarded_graph/workflow.py` | LangGraph routing, authorization, lexical evaluation, bounded retry, and response boundary |
| `src/guarded_graph/cli.py` | Offline demonstration interface |
| `tests/test_workflow.py` | Positive, negative, isolation, and failure-path checks |
