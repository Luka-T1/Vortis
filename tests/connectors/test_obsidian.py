"""Tests for ObsidianConnector — filesystem Markdown vault connector."""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from vortis.connectors._stubs import Document
from vortis.core.registry import ConnectorRegistry


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    """Build a minimal Obsidian vault under *tmp_path*."""
    (tmp_path / "note1.md").write_text(
        "---\n"
        "title: My First Note\n"
        "tags: [research, ai]\n"
        "---\n"
        "# My First Note\n\n"
        "This is the body of the first note.\n",
        encoding="utf-8",
    )

    (tmp_path / "note2.md").write_text(
        "# Plain Note\n\nNo frontmatter here.\n",
        encoding="utf-8",
    )

    subdir = tmp_path / "subdir"
    subdir.mkdir()
    (subdir / "deep.md").write_text(
        "# Deep Note\n\nNested file content.\n",
        encoding="utf-8",
    )

    hidden = tmp_path / ".obsidian"
    hidden.mkdir()
    (hidden / "config.json").write_text('{"theme": "dark"}\n', encoding="utf-8")

    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    return tmp_path


def _sync_all(vault_path: Path) -> List[Document]:
    """Import connector (triggers registry) and collect all docs."""
    from vortis.connectors.obsidian import ObsidianConnector  # noqa: PLC0415

    conn = ObsidianConnector(vault_path=str(vault_path))
    return list(conn.sync())


def test_is_connected(vault: Path) -> None:
    from vortis.connectors.obsidian import ObsidianConnector

    conn = ObsidianConnector(vault_path=str(vault))
    assert conn.is_connected() is True


def test_not_connected_bad_path() -> None:
    from vortis.connectors.obsidian import ObsidianConnector

    conn = ObsidianConnector(vault_path="/nonexistent/path/that/does/not/exist")
    assert conn.is_connected() is False


def test_sync_yields_markdown_files(vault: Path) -> None:
    """sync() yields all .md files including those in subdirectories."""
    docs = _sync_all(vault)
    assert len(docs) == 3


def test_sync_skips_hidden_dirs(vault: Path) -> None:
    """Files inside .obsidian (and other hidden dirs) are not yielded."""
    docs = _sync_all(vault)
    rel_paths = [d.url or "" for d in docs]
    assert not any(".obsidian" in p for p in rel_paths)
    assert not any(d.title == "config" for d in docs)


def test_sync_skips_binary_files(vault: Path) -> None:
    """Non-text files (.png, .jpg, etc.) are skipped entirely."""
    docs = _sync_all(vault)
    assert not any(d.doc_id.endswith(".png") for d in docs)
    assert not any("image" in d.doc_id for d in docs)


def test_sync_parses_frontmatter(vault: Path) -> None:
    """note1.md frontmatter title is used; tags land in metadata."""
    docs = _sync_all(vault)
    note1 = next(d for d in docs if "note1" in d.doc_id)
    assert note1.title == "My First Note"
    assert note1.metadata.get("tags") == ["research", "ai"]


def test_sync_sets_doc_type_note(vault: Path) -> None:
    """Every yielded document has doc_type='note' and source='obsidian'."""
    docs = _sync_all(vault)
    assert len(docs) > 0
    for doc in docs:
        assert doc.doc_type == "note"
        assert doc.source == "obsidian"


def test_disconnect(vault: Path) -> None:
    from vortis.connectors.obsidian import ObsidianConnector

    conn = ObsidianConnector(vault_path=str(vault))
    assert conn.is_connected() is True
    conn.disconnect()
    assert conn.is_connected() is False


def test_registry() -> None:
    """ObsidianConnector can be registered and retrieved via ConnectorRegistry."""
    from vortis.connectors.obsidian import ObsidianConnector  # noqa: PLC0415

    ConnectorRegistry.register_value("obsidian", ObsidianConnector)
    assert ConnectorRegistry.contains("obsidian")
    cls = ConnectorRegistry.get("obsidian")
    assert cls.connector_id == "obsidian"
