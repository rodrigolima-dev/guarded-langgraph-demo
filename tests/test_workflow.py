import unittest

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda
from langsmith import get_tracing_context, tracing_context

from guarded_graph import LocalCorpus, Principal, build_graph, run_query, sample_corpus


class GuardedGraphTests(unittest.TestCase):
    def setUp(self):
        self.alpha = Principal("sample-user", frozenset({"tenant-alpha"}))
        self.graph = build_graph(sample_corpus())

    def test_authorized_query_returns_only_scoped_published_sources(self):
        result = run_query(self.graph, self.alpha, "tenant-alpha", "schema")

        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["sources"], ["sample-alpha-01"])
        self.assertIn("schema", result["answer"].lower())
        self.assertEqual(set(result), {"status", "answer", "sources"})

    def test_cross_tenant_request_never_calls_retrieval_or_responder(self):
        class RejectUnexpectedRead:
            def has_tenant(self, tenant_id):
                return True

            def retrieve(self, tenant_id, query, limit=3):
                raise AssertionError("unauthorized retrieval")

        def unexpected_response(documents):
            raise AssertionError("unauthorized responder call")

        graph = build_graph(RejectUnexpectedRead(), RunnableLambda(unexpected_response))
        result = run_query(graph, self.alpha, "tenant-beta", "reports")

        self.assertEqual(result, {"status": "denied", "answer": "", "sources": []})

    def test_unknown_tenant_fails_closed_even_when_named_in_membership(self):
        principal = Principal("sample-user", frozenset({"tenant-unknown"}))
        result = run_query(self.graph, principal, "tenant-unknown", "schema")

        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["sources"], [])

    def test_blank_or_oversized_query_is_rejected_before_retrieval(self):
        for query in ("  ", "x" * 161, "\n"):
            with self.subTest(query=query[:20]):
                result = run_query(self.graph, self.alpha, "tenant-alpha", query)
                self.assertEqual(result["status"], "invalid_request")
                self.assertEqual(result["sources"], [])

    def test_unpublished_and_misfiled_documents_are_never_returned(self):
        corpus = LocalCorpus({
            "tenant-alpha": [
                Document(page_content="routingmarker draft", metadata={"tenant_id": "tenant-alpha", "source_id": "draft", "published": False}),
                Document(page_content="routingmarker foreign", metadata={"tenant_id": "tenant-beta", "source_id": "foreign", "published": True}),
                Document(page_content="routingmarker approved", metadata={"tenant_id": "tenant-alpha", "source_id": "approved", "published": True}),
            ]
        })
        result = run_query(build_graph(corpus), self.alpha, "tenant-alpha", "routingmarker")

        self.assertEqual(result["sources"], ["approved"])
        self.assertNotIn("draft", result["answer"])
        self.assertNotIn("foreign", result["answer"])

    def test_no_matches_skip_responder(self):
        def unexpected_response(documents):
            raise AssertionError("responder should not run")

        graph = build_graph(sample_corpus(), RunnableLambda(unexpected_response))
        result = run_query(graph, self.alpha, "tenant-alpha", "unmatchedword")

        self.assertEqual(result, {"status": "no_context", "answer": "", "sources": []})

    def test_allowed_plural_query_recovers_with_one_scoped_retry(self):
        class RecordingCorpus:
            def __init__(self):
                self.queries = []

            def has_tenant(self, tenant_id):
                return tenant_id == "tenant-alpha"

            def retrieve(self, tenant_id, query, limit=3):
                self.queries.append((tenant_id, query, limit))
                if query == "alert":
                    return (Document(
                        page_content="A sample alert is reviewed offline.",
                        metadata={"tenant_id": "tenant-alpha", "source_id": "sample-alert", "published": True},
                    ),)
                return ()

        corpus = RecordingCorpus()
        graph = build_graph(corpus)

        result = run_query(graph, self.alpha, "tenant-alpha", "alerts")
        with tracing_context(enabled=False):
            state = graph.invoke({"principal": self.alpha, "tenant_id": "tenant-alpha", "query": "alerts"})

        self.assertEqual(result["sources"], ["sample-alert"])
        self.assertEqual(corpus.queries[:2], [
            ("tenant-alpha", "alerts", 3),
            ("tenant-alpha", "alert", 3),
        ])
        self.assertEqual(state["retrieval_attempts"], 2)
        self.assertEqual(state["query"], "alerts")
        self.assertEqual(state["status"], "answered")

    def test_no_context_stops_after_at_most_two_reads(self):
        class EmptyCorpus:
            def __init__(self):
                self.queries = []

            def has_tenant(self, tenant_id):
                return True

            def retrieve(self, tenant_id, query, limit=3):
                self.queries.append((tenant_id, query))
                return ()

        corpus = EmptyCorpus()
        graph = build_graph(corpus)
        result = run_query(graph, self.alpha, "tenant-alpha", "alerts")

        self.assertEqual(result, {"status": "no_context", "answer": "", "sources": []})
        self.assertEqual(corpus.queries, [("tenant-alpha", "alerts"), ("tenant-alpha", "alert")])

    def test_untransformable_query_does_not_retry(self):
        class EmptyCorpus:
            def __init__(self):
                self.calls = 0

            def has_tenant(self, tenant_id):
                return True

            def retrieve(self, tenant_id, query, limit=3):
                self.calls += 1
                return ()

        corpus = EmptyCorpus()
        result = run_query(build_graph(corpus), self.alpha, "tenant-alpha", "unmatchedword")

        self.assertEqual(result["status"], "no_context")
        self.assertEqual(corpus.calls, 1)

    def test_denied_plural_query_does_not_read_tenant_catalog_or_documents(self):
        class NoReadCorpus:
            def has_tenant(self, tenant_id):
                raise AssertionError("denied request must not read catalog")

            def retrieve(self, tenant_id, query, limit=3):
                raise AssertionError("denied request must not read documents")

        result = run_query(build_graph(NoReadCorpus()), self.alpha, "tenant-beta", "reports")

        self.assertEqual(result, {"status": "denied", "answer": "", "sources": []})

    def test_misfiled_retry_documents_never_reach_responder(self):
        class MisfiledCorpus:
            def __init__(self):
                self.calls = 0

            def has_tenant(self, tenant_id):
                return True

            def retrieve(self, tenant_id, query, limit=3):
                self.calls += 1
                return (Document(
                    page_content="A sample alert belongs to another tenant.",
                    metadata={"tenant_id": "tenant-beta", "source_id": "foreign", "published": True},
                ),)

        def unexpected_response(documents):
            raise AssertionError("misfiled document must not reach response")

        corpus = MisfiledCorpus()
        result = run_query(build_graph(corpus, RunnableLambda(unexpected_response)), self.alpha, "tenant-alpha", "alerts")

        self.assertEqual(result, {"status": "no_context", "answer": "", "sources": []})
        self.assertEqual(corpus.calls, 2)

    def test_second_read_failure_fails_closed_without_response(self):
        class FailingRetryCorpus:
            def __init__(self):
                self.calls = 0

            def has_tenant(self, tenant_id):
                return True

            def retrieve(self, tenant_id, query, limit=3):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("synthetic retry failure")
                return ()

        corpus = FailingRetryCorpus()
        result = run_query(build_graph(corpus), self.alpha, "tenant-alpha", "alerts")

        self.assertEqual(result, {"status": "retrieval_error", "answer": "", "sources": []})
        self.assertEqual(corpus.calls, 2)

    def test_irrelevant_scoped_document_is_not_answered(self):
        class IrrelevantCorpus:
            def has_tenant(self, tenant_id):
                return True

            def retrieve(self, tenant_id, query, limit=3):
                return (Document(
                    page_content="A fictional unrelated queue item.",
                    metadata={"tenant_id": tenant_id, "source_id": "unrelated", "published": True},
                ),)

        result = run_query(build_graph(IrrelevantCorpus()), self.alpha, "tenant-alpha", "alerts")

        self.assertEqual(result, {"status": "no_context", "answer": "", "sources": []})

    def test_responder_receives_only_bounded_scoped_documents(self):
        observed = []

        def record_response(documents):
            observed.extend(documents)
            return "offline result"

        corpus = LocalCorpus({
            "tenant-alpha": [
                Document(page_content=f"queue sample {number}", metadata={"tenant_id": "tenant-alpha", "source_id": f"a-{number}", "published": True})
                for number in range(5)
            ],
            "tenant-beta": [
                Document(page_content="queue sample beta", metadata={"tenant_id": "tenant-beta", "source_id": "b-1", "published": True}),
            ],
        })
        graph = build_graph(corpus, RunnableLambda(record_response))
        result = run_query(graph, self.alpha, "tenant-alpha", "queue")

        self.assertEqual(result["answer"], "offline result")
        self.assertEqual(len(observed), 3)
        self.assertTrue(all(doc.metadata["tenant_id"] == "tenant-alpha" for doc in observed))
        self.assertEqual(len(result["sources"]), 3)

    def test_responder_failure_has_no_answer_or_sources(self):
        def broken_response(documents):
            raise RuntimeError("synthetic failure")

        graph = build_graph(sample_corpus(), RunnableLambda(broken_response))
        result = run_query(graph, self.alpha, "tenant-alpha", "schema")

        self.assertEqual(result, {"status": "response_error", "answer": "", "sources": []})

    def test_retrieval_failure_has_no_answer_or_sources(self):
        class BrokenCorpus:
            def has_tenant(self, tenant_id):
                return True

            def retrieve(self, tenant_id, query, limit=3):
                raise RuntimeError("synthetic internal detail")

        result = run_query(build_graph(BrokenCorpus()), self.alpha, "tenant-alpha", "schema")

        self.assertEqual(result, {"status": "retrieval_error", "answer": "", "sources": []})

    def test_tenant_catalog_failure_fails_closed(self):
        class BrokenCatalog:
            def has_tenant(self, tenant_id):
                raise RuntimeError("synthetic catalog detail")

            def retrieve(self, tenant_id, query, limit=3):
                raise AssertionError("retrieval must not run")

        result = run_query(build_graph(BrokenCatalog()), self.alpha, "tenant-alpha", "schema")

        self.assertEqual(result, {"status": "authorization_error", "answer": "", "sources": []})

    def test_second_tenant_has_its_own_positive_path(self):
        beta = Principal("sample-beta-user", frozenset({"tenant-beta"}))
        result = run_query(self.graph, beta, "tenant-beta", "report")

        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["sources"], ["sample-beta-01"])

    def test_langsmith_tracing_is_disabled_during_graph_execution(self):
        trace_state = []

        def inspect_trace(documents):
            trace_state.append(get_tracing_context().get("enabled"))
            return "offline result"

        graph = build_graph(sample_corpus(), RunnableLambda(inspect_trace))
        result = run_query(graph, self.alpha, "tenant-alpha", "schema")

        self.assertEqual(result["status"], "answered")
        self.assertEqual(trace_state, [False])


if __name__ == "__main__":
    unittest.main()
