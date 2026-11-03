"""Tests for GContactsConnector — OAuth-authenticated Google Contacts sync connector.

All People API calls are mocked; no network access is required.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from vortis.connectors._stubs import Document
from vortis.core.registry import ConnectorRegistry

_CONNECTIONS_RESPONSE = {
    "connections": [
        {
            "resourceName": "people/c1",
            "names": [{"displayName": "Alice Smith"}],
            "emailAddresses": [{"value": "alice@co.com"}],
            "phoneNumbers": [{"value": "+1-555-0100"}],
            "organizations": [{"name": "Acme Corp", "title": "VP Engineering"}],
        },
        {
            "resourceName": "people/c2",
            "names": [{"displayName": "Bob Jones"}],
            "emailAddresses": [{"value": "bob@co.com"}],
            "phoneNumbers": [],
            "organizations": [{"name": "Acme Corp", "title": "Designer"}],
        },
    ],
    "nextPageToken": None,
}


def _make_credentials(tmp_path: Path) -> Path:
    """Write a minimal fake credentials file and return its path."""
    creds = tmp_path / "gcontacts.json"
    creds.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")
    return creds


@pytest.fixture()
def connector(tmp_path: Path):
    """GContactsConnector pointing at a tmp credentials path (no file yet)."""
    from vortis.connectors.gcontacts import GContactsConnector  # noqa: PLC0415

    creds_path = str(tmp_path / "gcontacts.json")
    return GContactsConnector(credentials_path=creds_path)


def test_not_connected(connector) -> None:
    """is_connected() returns False when no credentials file exists."""
    assert connector.is_connected() is False


def test_auth_url(connector) -> None:
    """auth_url() returns the credentials page when no client_id is stored."""
    url = connector.auth_url()
    assert isinstance(url, str)
    assert url == "https://console.cloud.google.com/apis/credentials"


@patch("vortis.connectors.gcontacts._gcontacts_api_list")
def test_sync_yields_contacts(
    mock_list,
    connector,
    tmp_path: Path,
) -> None:
    """sync() yields one Document per contact with correct metadata."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")

    mock_list.return_value = _CONNECTIONS_RESPONSE

    docs: List[Document] = list(connector.sync())

    assert len(docs) == 2

    doc1 = next(d for d in docs if d.doc_id == "gcontacts:people/c1")
    assert doc1.source == "gcontacts"
    assert doc1.doc_type == "contact"
    assert doc1.title == "Alice Smith"
    assert doc1.author == "alice@co.com"
    assert "alice@co.com" in doc1.content
    assert "Acme Corp" in doc1.content

    doc2 = next(d for d in docs if d.doc_id == "gcontacts:people/c2")
    assert doc2.doc_type == "contact"
    assert doc2.title == "Bob Jones"
    assert doc2.author == "bob@co.com"
    assert "bob@co.com" in doc2.content
    assert "Acme Corp" in doc2.content

    mock_list.assert_called_once()


def test_disconnect(connector, tmp_path: Path) -> None:
    """disconnect() deletes the credentials file."""
    creds_path = Path(connector._credentials_path)
    creds_path.write_text(json.dumps({"token": "fake-access-token"}), encoding="utf-8")
    assert connector.is_connected() is True

    connector.disconnect()

    assert not creds_path.exists()
    assert connector.is_connected() is False


def test_mcp_tools(connector) -> None:
    """mcp_tools() returns exactly 2 tools with the required names."""
    tools = connector.mcp_tools()
    names = {t.name for t in tools}
    assert len(tools) == 2
    assert "contacts_find" in names
    assert "contacts_get_info" in names


def test_registry() -> None:
    """GContactsConnector can be registered and retrieved via ConnectorRegistry."""
    from vortis.connectors.gcontacts import GContactsConnector  # noqa: PLC0415

    ConnectorRegistry.register_value("gcontacts", GContactsConnector)
    assert ConnectorRegistry.contains("gcontacts")
    cls = ConnectorRegistry.get("gcontacts")
    assert cls.connector_id == "gcontacts"
