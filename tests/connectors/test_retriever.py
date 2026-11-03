"""Tests for TwoStageRetriever — BM25 recall + optional semantic reranking."""

from __future__ import annotations

from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest

from vortis.connectors.retriever import ColBERTReranker, Reranker, TwoStageRetriever
from vortis.connectors.store import KnowledgeStore
from vortis.tools.storage._stubs import RetrievalResult


def _has_torch() -> bool:
    try:
        import torch  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.fixture()
def store(tmp_path: Path) -> KnowledgeStore:
    """KnowledgeStore pre-populated with 4 items across different sources/authors."""
    ks = KnowledgeStore(db_path=tmp_path / "test_retriever.db")

    ks.store(
        content="AI research on neural networks and deep learning advances.",
        source="gmail",
        doc_type="email",
        author="alice@example.com",
    )
    ks.store(
        content="AI research on distributed systems and cloud infrastructure.",
        source="obsidian",
        doc_type="note",
        author="bob@example.com",
    )
    ks.store(
        content="AI research on natural language processing and transformers.",
        source="gmail",
        doc_type="email",
        author="alice@example.com",
    )
    ks.store(
        content="AI research on reinforcement learning for robotics.",
        source="slack",
        doc_type="message",
        author="carol@example.com",
    )

    return ks


@pytest.fixture()
def retriever(store: KnowledgeStore) -> TwoStageRetriever:
    return TwoStageRetriever(store)


def test_retrieve_returns_results(retriever: TwoStageRetriever) -> None:
    """A matching query returns at least one result."""
    results = retriever.retrieve("AI research")
    assert isinstance(results, list)
    assert len(results) >= 1
    assert all(isinstance(r, RetrievalResult) for r in results)


def test_retrieve_respects_top_k(retriever: TwoStageRetriever) -> None:
    """retrieve() returns at most top_k results."""
    results = retriever.retrieve("AI research", top_k=2)
    assert len(results) <= 2


def test_retrieve_with_source_filter(
    store: KnowledgeStore,
) -> None:
    """source= filter is forwarded to the KnowledgeStore."""
    ret = TwoStageRetriever(store)
    results = ret.retrieve("AI research", source="gmail")
    assert len(results) >= 1
    for r in results:
        assert r.metadata.get("source") == "gmail"


def test_retrieve_with_author_filter(
    store: KnowledgeStore,
) -> None:
    """author= filter is forwarded to the KnowledgeStore."""
    ret = TwoStageRetriever(store)
    results = ret.retrieve("AI research", author="alice@example.com")
    assert len(results) >= 1
    for r in results:
        assert r.metadata.get("author") == "alice@example.com"


def test_retrieve_bm25_only_when_no_reranker(
    store: KnowledgeStore,
) -> None:
    """Without a reranker the retriever returns BM25 results directly."""
    ret = TwoStageRetriever(store, reranker=None)
    results = ret.retrieve("AI research", top_k=3)
    assert isinstance(results, list)
    assert len(results) <= 3


def test_retrieve_with_colbert_reranking(
    store: KnowledgeStore,
) -> None:
    """When a reranker is provided it is called to reorder candidates."""
    mock_reranker = MagicMock(spec=Reranker)
    reranked = [
        RetrievalResult(
            content="Reranked result A",
            score=0.99,
            source="gmail",
            metadata={"reranked": True},
        ),
        RetrievalResult(
            content="Reranked result B",
            score=0.95,
            source="slack",
            metadata={"reranked": True},
        ),
    ]
    mock_reranker.rerank.return_value = reranked

    ret = TwoStageRetriever(store, reranker=mock_reranker, recall_k=4)
    results = ret.retrieve("AI research", top_k=2)

    mock_reranker.rerank.assert_called_once()
    call_args = mock_reranker.rerank.call_args
    assert call_args[1].get("top_k") == 2

    assert results == reranked


def test_retrieve_no_results(retriever: TwoStageRetriever) -> None:
    """A query matching nothing returns an empty list."""
    results = retriever.retrieve("xyzzy_nonexistent_zqjwkm")
    assert results == []


def test_retrieve_recall_k_larger_than_top_k(
    store: KnowledgeStore,
) -> None:
    """Stage-1 recall fetches max(recall_k, top_k*3) candidates."""
    call_log: List[int] = []

    class SpyStore(KnowledgeStore):
        def retrieve(self, query, *, top_k=5, **kwargs):  # type: ignore[override]
            call_log.append(top_k)
            return super().retrieve(query, top_k=top_k, **kwargs)

    spy = SpyStore(db_path=":memory:")
    spy.store(
        content="Deep learning research in computer vision tasks.",
        source="gmail",
        doc_type="email",
        author="alice@example.com",
    )

    ret = TwoStageRetriever(spy, recall_k=50)
    ret.retrieve("deep learning research", top_k=2)

    assert len(call_log) == 1
    assert call_log[0] == 50


@pytest.mark.skipif(
    not _has_torch(),
    reason="torch required for embedding tests",
)
def test_reranker_uses_cached_embeddings() -> None:
    """ColBERTReranker checks EmbeddingStore.get() before calling docFromText().

    When a cached embedding is found, docFromText() should NOT be called for
    that candidate.
    """
    import torch  # type: ignore[import]

    cached_emb = torch.randn(20, 128)

    mock_store = MagicMock()
    mock_store.get.return_value = cached_emb

    reranker = ColBERTReranker(embedding_store=mock_store)

    mock_model = MagicMock()
    mock_model.queryFromText.return_value = [torch.randn(32, 128)]
    reranker._model = mock_model

    candidates = [
        RetrievalResult(
            content="Some document about AI",
            score=1.0,
            source="gmail",
            metadata={"chunk_id": "chunk-123"},
        ),
    ]

    results = reranker.rerank("AI research", candidates, top_k=1)

    mock_store.get.assert_called_once_with("chunk-123")

    mock_model.docFromText.assert_not_called()

    assert len(results) == 1


@pytest.mark.skipif(
    not _has_torch(),
    reason="torch required for embedding tests",
)
def test_reranker_caches_new_embeddings() -> None:
    """When EmbeddingStore.get() returns None, docFromText() is called and
    the result is stored back via EmbeddingStore.store()."""
    import torch  # type: ignore[import]

    mock_store = MagicMock()
    mock_store.get.return_value = None

    reranker = ColBERTReranker(embedding_store=mock_store)

    mock_model = MagicMock()
    mock_model.queryFromText.return_value = [torch.randn(32, 128)]
    doc_emb = torch.randn(1, 20, 128)
    mock_model.docFromText.return_value = [doc_emb]
    reranker._model = mock_model

    candidates = [
        RetrievalResult(
            content="Document about neural nets",
            score=1.0,
            source="obsidian",
            metadata={"chunk_id": "chunk-456"},
        ),
    ]

    results = reranker.rerank("neural nets", candidates, top_k=1)

    mock_model.docFromText.assert_called_once()

    mock_store.store.assert_called_once()
    call_args = mock_store.store.call_args
    assert call_args[0][0] == "chunk-456"
    assert call_args[0][1].shape == (20, 128)

    assert len(results) == 1
