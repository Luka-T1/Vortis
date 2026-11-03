"""Tests for AppleNotesConnector — local macOS Notes database connector.

All tests use a temporary SQLite database that mimics the real NoteStore.sqlite
schema.  No actual macOS Notes database is required.
"""

from __future__ import annotations

import gzip
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

from vortis.connectors._stubs import Document
from vortis.core.registry import ConnectorRegistry


def _create_fake_notes_db(db_path: Path) -> None:
    """Populate a SQLite file with the Apple Notes schema and sample rows."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE TEXT,
            ZTITLE1 TEXT,
            ZMODIFICATIONDATE REAL,
            ZIDENTIFIER TEXT,
            ZNOTE INTEGER
        );
        CREATE TABLE ZICNOTEDATA (
            Z_PK INTEGER PRIMARY KEY,
            ZDATA BLOB,
            ZNOTE INTEGER
        );
    """
    )

    html1 = "<html><body><h1>Shopping List</h1><p>Milk, eggs, bread</p></body></html>"
    compressed1 = gzip.compress(html1.encode())
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES "
        "(1, NULL, 'Shopping List', 694310400.0, 'note-001', 1)"
    )
    conn.execute("INSERT INTO ZICNOTEDATA VALUES (1, ?, 1)", (compressed1,))

    html2 = "<html><body><p>Meeting notes from Monday</p></body></html>"
    compressed2 = gzip.compress(html2.encode())
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES "
        "(2, NULL, 'Meeting Notes', 694396800.0, 'note-002', 2)"
    )
    conn.execute("INSERT INTO ZICNOTEDATA VALUES (2, ?, 2)", (compressed2,))

    conn.commit()
    conn.close()


@pytest.fixture()
def fake_db(tmp_path: Path) -> Path:
    """Return path to a populated fake NoteStore.sqlite."""
    db_path = tmp_path / "NoteStore.sqlite"
    _create_fake_notes_db(db_path)
    return db_path


@pytest.fixture()
def connector(fake_db: Path):
    """AppleNotesConnector pointing at the fake DB."""
    from vortis.connectors.apple_notes import AppleNotesConnector  # noqa: PLC0415

    return AppleNotesConnector(db_path=str(fake_db))


def test_is_connected(connector) -> None:
    """is_connected() returns True when NoteStore.sqlite exists."""
    assert connector.is_connected() is True


def test_not_connected_missing_db() -> None:
    """is_connected() returns False when the database file does not exist."""
    from vortis.connectors.apple_notes import AppleNotesConnector  # noqa: PLC0415

    conn = AppleNotesConnector(db_path="/nonexistent/path/NoteStore.sqlite")
    assert conn.is_connected() is False


def test_sync_yields_notes(connector) -> None:
    """sync() yields one Document per note (2 total)."""
    docs: List[Document] = list(connector.sync())
    assert len(docs) == 2
    for doc in docs:
        assert doc.source == "apple_notes"
        assert doc.doc_type == "note"


def test_sync_decompresses_content(connector) -> None:
    """sync() produces plain text with no HTML tags in content."""
    docs: List[Document] = list(connector.sync())

    for doc in docs:
        assert "<" not in doc.content
        assert ">" not in doc.content

    contents = {d.content for d in docs}
    combined = " ".join(contents)
    assert "Shopping List" in combined or "Milk" in combined or "eggs" in combined
    assert "Meeting notes" in combined


def test_sync_sets_doc_type_note(connector) -> None:
    """All documents yielded by sync() have doc_type == 'note'."""
    docs: List[Document] = list(connector.sync())
    for doc in docs:
        assert doc.doc_type == "note"


def test_sync_doc_ids_and_titles(connector) -> None:
    """sync() sets doc_id from ZIDENTIFIER and title from ZTITLE."""
    docs: List[Document] = list(connector.sync())

    doc1 = next(d for d in docs if d.doc_id == "apple_notes:note-001")
    assert doc1.title == "Shopping List"

    doc2 = next(d for d in docs if d.doc_id == "apple_notes:note-002")
    assert doc2.title == "Meeting Notes"


def test_disconnect(connector) -> None:
    """disconnect() marks the connector as disconnected."""
    assert connector.is_connected() is True
    connector.disconnect()
    assert connector._connected is False


def test_mcp_tools(connector) -> None:
    """mcp_tools() returns exactly 2 tools with the expected names."""
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert len(tools) == 2
    assert "notes_search" in names
    assert "notes_get_note" in names


def test_registry() -> None:
    """AppleNotesConnector is registered and retrievable via ConnectorRegistry."""
    from vortis.connectors.apple_notes import AppleNotesConnector  # noqa: PLC0415

    ConnectorRegistry.register_value("apple_notes", AppleNotesConnector)
    assert ConnectorRegistry.contains("apple_notes")
    cls = ConnectorRegistry.get("apple_notes")
    assert cls.connector_id == "apple_notes"


def test_incremental_sync_uses_modern_note_modification_date(tmp_path: Path) -> None:
    """Modern Notes rows use ZMODIFICATIONDATE1 for incremental sync."""
    db_path = tmp_path / "ModernNoteStore.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE ZICCLOUDSYNCINGOBJECT (
            Z_PK INTEGER PRIMARY KEY,
            ZTITLE TEXT,
            ZTITLE1 TEXT,
            ZMODIFICATIONDATE REAL,
            ZMODIFICATIONDATE1 REAL,
            ZIDENTIFIER TEXT
        );
        CREATE TABLE ZICNOTEDATA (
            Z_PK INTEGER PRIMARY KEY,
            ZDATA BLOB,
            ZNOTE INTEGER
        );
    """
    )
    compressed = gzip.compress(b"<p>New movie list</p>")
    conn.execute(
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES "
        "(1, NULL, 'Movies', NULL, 800000000.0, 'note-modern')"
    )
    conn.execute("INSERT INTO ZICNOTEDATA VALUES (1, ?, 1)", (compressed,))
    conn.commit()
    conn.close()

    from vortis.connectors.apple_notes import AppleNotesConnector  # noqa: PLC0415

    connector = AppleNotesConnector(db_path=str(db_path))
    docs = list(connector.sync(since=datetime(2026, 1, 1, tzinfo=timezone.utc)))

    assert [doc.doc_id for doc in docs] == ["apple_notes:note-modern"]


def test_incremental_sync_falls_back_to_legacy_modification_date(connector) -> None:
    """Older Notes rows continue to use ZMODIFICATIONDATE."""
    docs = list(connector.sync(since=datetime(2023, 1, 1, tzinfo=timezone.utc)))

    assert {doc.doc_id for doc in docs} == {
        "apple_notes:note-001",
        "apple_notes:note-002",
    }
