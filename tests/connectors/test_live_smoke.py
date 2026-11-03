"""Live smoke test — full pipeline with real markdown files.

NOT mocked. Uses the actual Vortis docs/ directory as an Obsidian-like vault.
Exercises: ObsidianConnector → SyncEngine → KnowledgeStore → knowledge_search tool.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from vortis.connectors.obsidian import ObsidianConnector
from vortis.connectors.pipeline import IngestionPipeline
from vortis.connectors.store import KnowledgeStore
from vortis.connectors.sync_engine import SyncEngine
from vortis.tools.knowledge_search import KnowledgeSearchTool

DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"


@pytest.mark.live
def test_live_obsidian_full_pipeline() -> None:
    """Smoke test: index real .md files, then search them."""
    assert DOCS_DIR.is_dir(), f"Docs dir not found: {DOCS_DIR}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        store = KnowledgeStore(db_path=str(tmp_path / "live.db"))
        pipeline = IngestionPipeline(store=store, max_tokens=256)
        engine = SyncEngine(
            pipeline=pipeline,
            state_db=str(tmp_path / "state.db"),
        )
        connector = ObsidianConnector(vault_path=str(DOCS_DIR))

        assert connector.is_connected(), "Connector should see docs dir"

        items = engine.sync(connector)
        print(f"\n  Synced {items} chunks from {DOCS_DIR}")
        assert items > 0, "Should have indexed some chunks"

        cp = engine.get_checkpoint("obsidian")
        assert cp is not None
        assert cp["items_synced"] > 0
        print(f"  Checkpoint: {cp['items_synced']} items synced")

        tool = KnowledgeSearchTool(store=store)

        result = tool.execute(query="agent")
        assert result.success, f"Search failed: {result.content}"
        assert result.metadata["num_results"] > 0
        print(f"  'agent' query: {result.metadata['num_results']} results")

        result = tool.execute(query="inference engine")
        assert result.success
        print(f"  'inference engine' query: {result.metadata['num_results']} results")

        result = tool.execute(query="agent", source="obsidian")
        assert result.success
        assert result.metadata["num_results"] > 0

        result = tool.execute(query="xyzzy999nonexistent")
        assert result.success
        assert "No relevant results" in result.content

        result = tool.execute(query="registry pattern")
        if result.metadata["num_results"] > 0:
            assert "[obsidian]" in result.content
            print("  'registry pattern': found with attribution")

        print(
            f"\n  SMOKE TEST PASSED — {items} chunks indexed, search working end-to-end"
        )
