"""Integration tests for ChannelAgent with DeepResearchAgent and KnowledgeStore.

Covers the full path:
  Documents
    -> IngestionPipeline
    -> KnowledgeStore
    -> TwoStageRetriever
    -> KnowledgeSearchTool
    -> DeepResearchAgent
    -> ChannelAgent
    -> FakeChannel (sent messages)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from vortis.agents.channel_agent import ChannelAgent
from vortis.agents.deep_research import DeepResearchAgent
from vortis.channels._stubs import BaseChannel, ChannelMessage, ChannelStatus
from vortis.connectors._stubs import Document
from vortis.connectors.pipeline import IngestionPipeline
from vortis.connectors.retriever import TwoStageRetriever
from vortis.connectors.store import KnowledgeStore
from vortis.tools.knowledge_search import KnowledgeSearchTool


class FakeChannel(BaseChannel):
    """Minimal in-process channel for integration tests."""

    channel_id = "fake"

    def __init__(self) -> None:
        self._handlers: List[Any] = []
        self._sent: List[Dict[str, Any]] = []

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        self._sent.append({"content": content, "conv": conversation_id})
        return True

    def status(self) -> ChannelStatus:
        return ChannelStatus.CONNECTED

    def list_channels(self) -> List[str]:
        return ["test"]

    def on_message(self, handler: Any) -> None:
        self._handlers.append(handler)

    def simulate(self, text: str) -> None:
        """Fire all registered handlers with a synthetic message."""
        msg = ChannelMessage(
            channel="fake",
            sender="user",
            content=text,
            conversation_id="conv1",
        )
        for h in self._handlers:
            h(msg)


_DOCS = [
    Document(
        doc_id="gcal-001",
        source="gcalendar",
        doc_type="event",
        content=(
            "Team sync meeting scheduled for Monday at 10am."
            " Attendees: alice, bob, carol."
        ),
        title="Team Sync",
        author="alice",
    ),
    Document(
        doc_id="slack-001",
        source="slack",
        doc_type="message",
        content=(
            "Budget discussion: we need to cut API costs by 20%."
            " Consider switching to a cheaper provider."
        ),
        title="Budget API discussion",
        author="bob",
    ),
    Document(
        doc_id="gmail-001",
        source="gmail",
        doc_type="email",
        content=(
            "Re: API redesign proposal — the new REST endpoints look good"
            " but we need to handle rate limits and review the budget impact."
        ),
        title="API redesign proposal",
        author="carol",
    ),
]


def _make_engine_response(
    content: str, tool_calls: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "content": content,
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 100,
            "total_tokens": 150,
        },
        "model": "test-model",
        "finish_reason": "stop",
    }
    if tool_calls:
        result["tool_calls"] = tool_calls
        result["finish_reason"] = "tool_calls"
    return result


def _build_store_and_tool(
    tmp_path: Path,
) -> tuple[KnowledgeStore, KnowledgeSearchTool]:
    """Ingest _DOCS and return (store, KnowledgeSearchTool)."""
    store = KnowledgeStore(db_path=str(tmp_path / "ca_integration.db"))
    pipeline = IngestionPipeline(store)
    chunks_stored = pipeline.ingest(_DOCS)
    assert chunks_stored >= 3, f"Expected >= 3 chunks, got {chunks_stored}"
    retriever = TwoStageRetriever(store)
    ks_tool = KnowledgeSearchTool(store=store, retriever=retriever)
    return store, ks_tool


def test_quick_query_inline_response(tmp_path: Path) -> None:
    """Quick query 'When is my next meeting?' receives an inline response
    containing calendar info and NO vortis:// link.
    """
    _store, ks_tool = _build_store_and_tool(tmp_path)

    mock_engine = MagicMock()
    mock_engine.engine_id = "mock"
    mock_engine.health.return_value = True
    mock_engine.generate.return_value = _make_engine_response(
        "Your next meeting is Team Sync on Monday at 10am with alice, bob, carol."
    )

    agent = DeepResearchAgent(mock_engine, "test-model", tools=[ks_tool])

    channel = FakeChannel()
    ca = ChannelAgent(channel, agent)

    channel.simulate("When is my next meeting?")

    time.sleep(1)
    ca.shutdown()

    assert len(channel._sent) == 1, (
        f"Expected exactly 1 sent message, got {len(channel._sent)}"
    )
    sent_content: str = channel._sent[0]["content"]

    assert "vortis://" not in sent_content, (
        f"Quick query must NOT produce an escalation link, but got:\n{sent_content}"
    )

    assert any(
        keyword in sent_content.lower()
        for keyword in ("meeting", "monday", "10am", "team sync", "sync")
    ), f"Response should contain meeting info, but got:\n{sent_content}"


def test_deep_query_escalation_link(tmp_path: Path) -> None:
    """Deep query about budget and API redesign triggers an escalation link."""
    _store, ks_tool = _build_store_and_tool(tmp_path)

    mock_engine = MagicMock()
    mock_engine.engine_id = "mock"
    mock_engine.health.return_value = True

    tool_call_response = _make_engine_response(
        "",
        tool_calls=[
            {
                "id": "call_budget_1",
                "type": "function",
                "function": {
                    "name": "knowledge_search",
                    "arguments": json.dumps({"query": "budget API redesign"}),
                },
            }
        ],
    )

    long_report = (
        "## Summary of Budget and API Redesign Discussions\n\n"
        "Based on cross-referencing Slack messages and email threads, "
        "the team has been actively discussing two related topics: "
        "budget cuts for API infrastructure and a proposed API redesign.\n\n"
        "**Budget Discussion (Slack):** Bob raised concerns about the current "
        "API costs, proposing a 20% reduction by switching to a cheaper provider. "
        "[slack] Budget API discussion -- bob\n\n"
        "**API Redesign (Email):** Carol's email review of the new REST endpoints "
        "highlighted the need to handle rate limits and assess the budget impact. "
        "[gmail] API redesign proposal -- carol\n\n"
        "## Sources\n"
        "- [slack] Budget API discussion -- bob\n"
        "- [gmail] API redesign proposal -- carol\n"
    )
    assert len(long_report) > 500, (
        f"Report must exceed 500 chars to trigger escalation, got {len(long_report)}"
    )

    final_response = _make_engine_response(long_report)
    mock_engine.generate.side_effect = [tool_call_response, final_response]

    agent = DeepResearchAgent(mock_engine, "test-model", tools=[ks_tool])

    channel = FakeChannel()
    ca = ChannelAgent(channel, agent)

    channel.simulate("Summarize all discussions about budget and API redesign")

    time.sleep(1)
    ca.shutdown()

    assert len(channel._sent) == 1, (
        f"Expected exactly 1 sent message, got {len(channel._sent)}"
    )
    sent_content: str = channel._sent[0]["content"]

    assert "vortis://" in sent_content, (
        f"Deep query must produce an escalation link, but got:\n{sent_content}"
    )
