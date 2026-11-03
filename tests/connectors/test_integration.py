"""Integration test: Obsidian vault → SyncEngine → KnowledgeStore → knowledge_search."""

from __future__ import annotations

from pathlib import Path

import pytest

from vortis.connectors.obsidian import ObsidianConnector
from vortis.connectors.pipeline import IngestionPipeline
from vortis.connectors.store import KnowledgeStore
from vortis.connectors.sync_engine import SyncEngine
from vortis.tools.knowledge_search import KnowledgeSearchTool


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "test-vault"
    vault_dir.mkdir()
    (vault_dir / "project-notes.md").write_text(
        "# Project Alpha\n\nWe decided to migrate to Kubernetes in March.\n\n"
        "## Cost Analysis\n\n"
        "Estimated 40% increase in cloud spend during transition.\n\n"
        "## Timeline\n\nSix-week migration window starting April 1st."
    )
    (vault_dir / "meeting.md").write_text(
        "# Sprint Review\n\nDiscussed budget concerns with Mike and Sarah.\n"
        "Action item: Sarah to prepare cost comparison document."
    )
    return vault_dir


def test_full_pipeline_obsidian_to_search(vault: Path, tmp_path: Path) -> None:
    """End-to-end: Obsidian vault → SyncEngine → KnowledgeStore → knowledge_search."""
    store = KnowledgeStore(db_path=str(tmp_path / "integration.db"))
    pipeline = IngestionPipeline(store=store)
    engine = SyncEngine(pipeline=pipeline, state_db=str(tmp_path / "state.db"))
    connector = ObsidianConnector(vault_path=str(vault))

    engine.sync(connector)

    cp = engine.get_checkpoint("obsidian")
    assert cp is not None
    assert cp["items_synced"] == 6

    tool = KnowledgeSearchTool(store=store)

    result = tool.execute(query="Kubernetes migration")
    assert result.success
    assert "Kubernetes" in result.content

    result = tool.execute(query="budget concerns")
    assert result.success
    assert "budget" in result.content.lower()

    result = tool.execute(query="migration", source="obsidian")
    assert result.success

    result = tool.execute(query="migration", source="gmail")
    assert "No relevant results" in result.content
