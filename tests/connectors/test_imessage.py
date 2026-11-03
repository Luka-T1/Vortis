"""Tests for IMessageConnector — local macOS Messages database connector.

All tests use a temporary SQLite database that mimics the real chat.db schema.
No actual macOS Messages database is required.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List

import pytest

from vortis.connectors._stubs import Document
from vortis.core.registry import ConnectorRegistry


def _create_fake_chat_db(db_path: Path) -> None:
    """Populate a SQLite file with the iMessage chat.db schema and sample rows."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        "CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT NOT NULL);"
        "CREATE TABLE chat ("
        "  ROWID INTEGER PRIMARY KEY,"
        "  chat_identifier TEXT NOT NULL,"
        "  display_name TEXT"
        ");"
        "CREATE TABLE message ("
        "  ROWID INTEGER PRIMARY KEY,"
        "  text TEXT,"
        "  handle_id INTEGER,"
        "  date INTEGER,"
        "  is_from_me INTEGER DEFAULT 0,"
        "  cache_roomnames TEXT"
        ");"
        "CREATE TABLE chat_message_join ("
        "  chat_id INTEGER,"
        "  message_id INTEGER"
        ");"
        "INSERT INTO handle VALUES (1, '+15550100');"
        "INSERT INTO handle VALUES (2, 'alice@icloud.com');"
        "INSERT INTO chat VALUES (1, '+15550100', 'Alice');"
        "INSERT INTO chat VALUES (2, 'chat123', 'Team Group');"
        "INSERT INTO message VALUES ("
        "  1, 'Hey, are we meeting tomorrow?',"
        "  1, 700000000000000000, 0, NULL"
        ");"
        "INSERT INTO message VALUES ("
        "  2, 'Yes at 3pm!', 1, 700000060000000000, 1, NULL"
        ");"
        "INSERT INTO message VALUES ("
        "  3, 'Group message about project',"
        "  2, 700000120000000000, 0, 'chat123'"
        ");"
        "INSERT INTO chat_message_join VALUES (1, 1);"
        "INSERT INTO chat_message_join VALUES (1, 2);"
        "INSERT INTO chat_message_join VALUES (2, 3);"
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def fake_db(tmp_path: Path) -> Path:
    """Return path to a populated fake chat.db."""
    db_path = tmp_path / "chat.db"
    _create_fake_chat_db(db_path)
    return db_path


@pytest.fixture()
def connector(fake_db: Path):
    """IMessageConnector pointing at the fake DB."""
    from vortis.connectors.imessage import IMessageConnector  # noqa: PLC0415

    return IMessageConnector(db_path=str(fake_db))


def test_is_connected(connector) -> None:
    """is_connected() returns True when chat.db exists at the configured path."""
    assert connector.is_connected() is True


def test_not_connected_missing_db() -> None:
    """is_connected() returns False when the database file does not exist."""
    from vortis.connectors.imessage import IMessageConnector  # noqa: PLC0415

    conn = IMessageConnector(db_path="/nonexistent/path/chat.db")
    assert conn.is_connected() is False


def test_sync_yields_messages(connector) -> None:
    """sync() yields one Document per non-NULL message (3 total)."""
    docs: List[Document] = list(connector.sync())
    assert len(docs) == 3
    for doc in docs:
        assert doc.source == "imessage"
        assert doc.doc_type == "message"


def test_sync_message_content(connector) -> None:
    """sync() surfaces the exact message text in each Document's content."""
    docs: List[Document] = list(connector.sync())
    contents = {d.content for d in docs}
    assert "Hey, are we meeting tomorrow?" in contents
    assert "Yes at 3pm!" in contents
    assert "Group message about project" in contents


def test_sync_sets_author(connector) -> None:
    """Received messages use the handle identifier; sent messages use 'me'."""
    docs: List[Document] = list(connector.sync())

    msg1 = next(d for d in docs if d.doc_id == "imessage:1")
    assert msg1.author == "+15550100"

    msg2 = next(d for d in docs if d.doc_id == "imessage:2")
    assert msg2.author == "me"

    msg3 = next(d for d in docs if d.doc_id == "imessage:3")
    assert msg3.author == "alice@icloud.com"


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
    assert "imessage_search_messages" in names
    assert "imessage_get_conversation" in names


def test_registry() -> None:
    """IMessageConnector is registered and retrievable via ConnectorRegistry."""
    from vortis.connectors.imessage import IMessageConnector  # noqa: PLC0415

    ConnectorRegistry.register_value("imessage", IMessageConnector)
    assert ConnectorRegistry.contains("imessage")
    cls = ConnectorRegistry.get("imessage")
    assert cls.connector_id == "imessage"
