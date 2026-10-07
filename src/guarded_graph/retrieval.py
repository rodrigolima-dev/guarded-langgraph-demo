import re
from collections.abc import Mapping, Sequence

from langchain_core.documents import Document


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


class LocalCorpus:
    """In-memory sample store partitioned by tenant before ranking."""

    def __init__(self, buckets: Mapping[str, Sequence[Document]]):
        self._buckets = {tenant_id: tuple(docs) for tenant_id, docs in buckets.items()}

    def has_tenant(self, tenant_id: str) -> bool:
        return tenant_id in self._buckets

    def retrieve(self, tenant_id: str, query: str, limit: int = 3) -> tuple[Document, ...]:
        words = _tokens(query)
        if tenant_id not in self._buckets or not words or limit < 1:
            return ()

        ranked: list[tuple[int, str, Document]] = []
        for document in self._buckets[tenant_id]:
            metadata = document.metadata
            source_id = metadata.get("source_id")
            if (
                metadata.get("tenant_id") != tenant_id
                or metadata.get("published") is not True
                or not isinstance(source_id, str)
                or not source_id
            ):
                continue
            score = len(words & _tokens(document.page_content))
            if score:
                ranked.append((score, source_id, document))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        return tuple(item[2] for item in ranked[: min(limit, 3)])


def sample_corpus() -> LocalCorpus:
    """Build an entirely fictional corpus; no external data source is read."""

    return LocalCorpus({
        "tenant-alpha": [
            Document(
                page_content="The sample ingestion job validates an event schema before writing to a local queue.",
                metadata={"tenant_id": "tenant-alpha", "source_id": "sample-alpha-01", "published": True},
            ),
            Document(
                page_content="A fictional reviewer checks a sample alert after a bounded retry decision.",
                metadata={"tenant_id": "tenant-alpha", "source_id": "sample-alpha-02", "published": True},
            ),
            Document(
                page_content="This draft example is intentionally unavailable to retrieval.",
                metadata={"tenant_id": "tenant-alpha", "source_id": "sample-alpha-draft", "published": False},
            ),
        ],
        "tenant-beta": [
            Document(
                page_content="The separate example tenant exports an offline report after a sample approval.",
                metadata={"tenant_id": "tenant-beta", "source_id": "sample-beta-01", "published": True},
            ),
        ],
    })
