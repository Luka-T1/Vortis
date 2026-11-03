"""Tests for EmbeddingStore — disk-persistent ColBERT token-level embeddings."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vortis.connectors.embedding_store import EmbeddingStore

torch = pytest.importorskip("torch", reason="torch required for embedding tests")


@pytest.fixture()
def emb_store(tmp_path: Path) -> EmbeddingStore:
    """An EmbeddingStore rooted at a temporary directory."""
    return EmbeddingStore(store_dir=str(tmp_path / "embeddings"))


def _make_tensor(rows: int = 20, cols: int = 128):
    """Create a dummy tensor (rows, cols) mimicking ColBERT token embeddings."""
    import torch  # type: ignore[import]

    return torch.randn(rows, cols)


def test_store_and_get(emb_store: EmbeddingStore) -> None:
    """Storing a tensor and getting it back preserves shape and values."""
    import torch  # type: ignore[import]

    tensor = _make_tensor(25, 128)
    emb_store.store("chunk-abc", tensor)

    loaded = emb_store.get("chunk-abc")
    assert loaded is not None
    assert loaded.shape == (25, 128)
    assert torch.allclose(tensor, loaded)


def test_has(emb_store: EmbeddingStore) -> None:
    """has() returns True for stored chunks, False for unknown ones."""
    assert emb_store.has("nonexistent") is False

    tensor = _make_tensor()
    emb_store.store("chunk-1", tensor)

    assert emb_store.has("chunk-1") is True
    assert emb_store.has("chunk-2") is False


def test_count(emb_store: EmbeddingStore) -> None:
    """count() tracks the number of stored embeddings."""
    assert emb_store.count() == 0

    emb_store.store("a", _make_tensor())
    assert emb_store.count() == 1

    emb_store.store("b", _make_tensor())
    assert emb_store.count() == 2


def test_delete(emb_store: EmbeddingStore) -> None:
    """delete() removes both the tensor file and the index entry."""
    tensor = _make_tensor()
    emb_store.store("chunk-del", tensor)
    assert emb_store.has("chunk-del") is True

    result = emb_store.delete("chunk-del")
    assert result is True
    assert emb_store.has("chunk-del") is False
    assert emb_store.get("chunk-del") is None
    assert emb_store.count() == 0


def test_delete_nonexistent(emb_store: EmbeddingStore) -> None:
    """delete() returns False for a chunk that was never stored."""
    assert emb_store.delete("nope") is False


def test_get_nonexistent(emb_store: EmbeddingStore) -> None:
    """get() returns None for an unknown chunk_id."""
    assert emb_store.get("does-not-exist") is None


def test_graceful_without_torch(tmp_path: Path) -> None:
    """When torch is not importable, all methods degrade gracefully."""
    store = EmbeddingStore(store_dir=str(tmp_path / "no_torch"))

    fake_tensor = MagicMock()

    import builtins

    real_import = builtins.__import__

    def _no_torch(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise ImportError("mocked: no torch")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_no_torch):
        store.store("chunk-x", fake_tensor)
        assert store.count() == 0

        assert store.get("chunk-x") is None


def test_store_overwrites(emb_store: EmbeddingStore) -> None:
    """Storing the same chunk_id twice overwrites the previous embedding."""
    import torch  # type: ignore[import]

    t1 = _make_tensor(10, 128)
    t2 = _make_tensor(15, 128)

    emb_store.store("chunk-ow", t1)
    emb_store.store("chunk-ow", t2)

    assert emb_store.count() == 1
    loaded = emb_store.get("chunk-ow")
    assert loaded is not None
    assert loaded.shape == (15, 128)
    assert torch.allclose(t2, loaded)
