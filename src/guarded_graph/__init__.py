"""Offline example of tenant-scoped retrieval with explicit graph gates."""

from .models import Principal
from .retrieval import LocalCorpus, sample_corpus
from .workflow import build_graph, run_query

__all__ = ["LocalCorpus", "Principal", "build_graph", "run_query", "sample_corpus"]
