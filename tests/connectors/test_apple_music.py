"""Tests for AppleMusicConnector -- local Music.app via AppleScript.

All tests mock ``subprocess.run`` so no actual Music.app interaction is needed.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from vortis.connectors._stubs import Document
from vortis.core.registry import ConnectorRegistry

_SAMPLE_OUTPUT = (
    "Bohemian Rhapsody|||Queen|||A Night at the Opera|||354.0|||Rock|||42|||"
    "Saturday, March 15, 2026 at 2:30:00 PM\n"
    "Blinding Lights|||The Weeknd|||After Hours|||200.0|||Pop|||18|||never\n"
)


@pytest.fixture()
def connector():
    """Return a fresh AppleMusicConnector."""
    from vortis.connectors.apple_music import AppleMusicConnector

    return AppleMusicConnector()


def test_apple_music_registered():
    """AppleMusicConnector is discoverable via ConnectorRegistry."""
    from vortis.connectors.apple_music import AppleMusicConnector

    ConnectorRegistry.register_value("apple_music", AppleMusicConnector)
    assert ConnectorRegistry.contains("apple_music")
    cls = ConnectorRegistry.get("apple_music")
    assert cls.connector_id == "apple_music"
    assert cls.display_name == "Apple Music"
    assert cls.auth_type == "local"


def test_is_connected_on_macos(connector):
    """is_connected() returns True on macOS when Music.app responds."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Library"

    with (
        patch("vortis.connectors.apple_music.sys") as mock_sys,
        patch("vortis.connectors.apple_music.subprocess") as mock_subprocess,
    ):
        mock_sys.platform = "darwin"
        mock_subprocess.run.return_value = mock_result
        mock_subprocess.TimeoutExpired = TimeoutError
        assert connector.is_connected() is True


def test_is_connected_on_linux(connector):
    """is_connected() returns False on non-macOS platforms."""
    with patch("vortis.connectors.apple_music.sys") as mock_sys:
        mock_sys.platform = "linux"
        assert connector.is_connected() is False


def test_sync_yields_tracks(connector):
    """sync() parses AppleScript output and yields correct Documents."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = _SAMPLE_OUTPUT

    with patch(
        "vortis.connectors.apple_music._run_osascript",
        return_value=_SAMPLE_OUTPUT,
    ):
        docs: List[Document] = list(connector.sync())

    assert len(docs) == 2
    assert all(isinstance(d, Document) for d in docs)
    assert all(d.source == "apple_music" for d in docs)
    assert all(d.doc_type == "track" for d in docs)

    assert docs[0].author == "Queen"
    assert "Bohemian Rhapsody" in docs[0].title
    content0 = json.loads(docs[0].content)
    assert content0["album"] == "A Night at the Opera"
    assert content0["play_count"] == 42
    assert docs[0].metadata["genre"] == "Rock"
    assert docs[0].metadata["duration_s"] == 354.0

    assert docs[1].author == "The Weeknd"
    assert "Blinding Lights" in docs[1].title
    content1 = json.loads(docs[1].content)
    assert content1["genre"] == "Pop"
    assert docs[1].metadata["play_count"] == 18


def test_sync_filters_by_since(connector):
    """sync(since=...) skips tracks with played_date before the threshold."""
    with patch(
        "vortis.connectors.apple_music._run_osascript",
        return_value=_SAMPLE_OUTPUT,
    ):
        docs = list(connector.sync(since=datetime(2026, 3, 16)))

    assert len(docs) == 1
    assert "Blinding Lights" in docs[0].title


def test_sync_handles_failure(connector):
    """sync() returns empty when AppleScript fails."""
    with patch(
        "vortis.connectors.apple_music._run_osascript",
        return_value=None,
    ):
        docs = list(connector.sync())

    assert len(docs) == 0
    assert connector.sync_status().state == "error"


def test_disconnect_is_noop(connector):
    """disconnect() does nothing (local connector)."""
    connector.disconnect()
