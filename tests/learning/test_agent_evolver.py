"""Tests for AgentConfigEvolver — trace-driven agent config evolution."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

from vortis.core.types import StepType, Trace, TraceStep
from vortis.learning.agents.agent_evolver import AgentConfigEvolver
from vortis.traces.store import TraceStore


def _make_trace(
    *,
    query: str = "hello",
    agent: str = "orchestrator",
    model: str = "qwen3:8b",
    tools: list[str] | None = None,
    outcome: str = "success",
    feedback: float = 0.9,
) -> Trace:
    """Build a Trace with TOOL_CALL steps for the given tool names."""
    steps: list[TraceStep] = []
    for tool_name in tools or []:
        steps.append(
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=time.time(),
                duration_seconds=0.1,
                input={"tool": tool_name, "args": {}},
                output={"result": "ok"},
            )
        )
    steps.append(
        TraceStep(
            step_type=StepType.GENERATE,
            timestamp=time.time(),
            duration_seconds=0.5,
            input={"prompt": query},
            output={"content": "answer", "tokens": 50},
        )
    )
    return Trace(
        query=query,
        agent=agent,
        model=model,
        steps=steps,
        result="answer",
        outcome=outcome,
        feedback=feedback,
        started_at=time.time(),
        ended_at=time.time() + 1.0,
        total_tokens=50,
        total_latency_seconds=0.6,
    )


class TestAgentConfigEvolver:
    def test_analyze_empty_store(self, tmp_path: Path) -> None:
        """Empty trace store returns empty recommendations."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        evolver = AgentConfigEvolver(store, config_dir=config_dir)
        recs = evolver.analyze()

        assert recs == []
        store.close()

    def test_evolve_recommends_tool_changes(self, tmp_path: Path) -> None:
        """Traces with different tools — best tools recommended for each query class."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        for i in range(5):
            t = _make_trace(
                query=f"calculate {i + 1} + {i + 2}",
                agent="orchestrator",
                tools=["calculator", "think"],
                outcome="success",
                feedback=0.95,
            )
            store.save(t)

        for i in range(5):
            t = _make_trace(
                query=f"Tell me a moderately long story about topic number {i} please",
                agent="orchestrator",
                tools=["web_search"],
                outcome="success",
                feedback=0.8,
            )
            store.save(t)

        for i in range(3):
            t = _make_trace(
                query=f"compute the integral of x^{i}",
                agent="simple",
                tools=["calculator"],
                outcome="success",
                feedback=0.6,
            )
            store.save(t)

        evolver = AgentConfigEvolver(store, config_dir=config_dir)
        recs = evolver.analyze()

        assert len(recs) > 0

        for rec in recs:
            assert "query_class" in rec
            assert "recommended_tools" in rec
            assert "recommended_agent" in rec
            assert "recommended_max_turns" in rec
            assert "sample_count" in rec
            assert rec["sample_count"] > 0

        math_recs = [r for r in recs if r["query_class"] == "math"]
        if math_recs:
            assert "calculator" in math_recs[0]["recommended_tools"]

        store.close()

    def test_write_config_creates_toml(self, tmp_path: Path) -> None:
        """write_config creates a valid TOML file with correct content."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        evolver = AgentConfigEvolver(store, config_dir=config_dir)
        path = evolver.write_config(
            "research_agent",
            tools=["web_search", "file_read", "think"],
            max_turns=15,
            temperature=0.4,
            system_prompt="You are a research assistant.",
        )

        assert path.exists()
        assert path.suffix == ".toml"
        assert "research_agent" in path.name

        with open(path, "rb") as f:
            data = tomllib.load(f)

        assert "agent" in data
        agent_cfg = data["agent"]
        assert agent_cfg["name"] == "research_agent"
        assert agent_cfg["tools"] == ["web_search", "file_read", "think"]
        assert agent_cfg["max_turns"] == 15
        assert agent_cfg["temperature"] == 0.4
        assert agent_cfg["system_prompt"] == "You are a research assistant."

        store.close()

    def test_versioning_and_rollback(self, tmp_path: Path) -> None:
        """Write v1, write v2, list versions, rollback to v1."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        evolver = AgentConfigEvolver(store, config_dir=config_dir)

        evolver.write_config(
            "my_agent",
            tools=["calculator"],
            max_turns=5,
            temperature=0.2,
            system_prompt="v1 prompt",
        )

        evolver.write_config(
            "my_agent",
            tools=["calculator", "web_search"],
            max_turns=10,
            temperature=0.5,
            system_prompt="v2 prompt",
        )

        config_path = config_dir / "my_agent.toml"
        with open(config_path, "rb") as f:
            current = tomllib.load(f)
        assert current["agent"]["tools"] == ["calculator", "web_search"]
        assert current["agent"]["system_prompt"] == "v2 prompt"

        versions = evolver.list_versions("my_agent")
        assert len(versions) >= 2
        for v in versions:
            assert "version" in v
            assert "path" in v
            assert "modified" in v
            assert isinstance(v["version"], int)
            assert os.path.exists(v["path"])

        evolver.rollback("my_agent", version=1)

        with open(config_path, "rb") as f:
            rolled_back = tomllib.load(f)
        assert rolled_back["agent"]["tools"] == ["calculator"]
        assert rolled_back["agent"]["system_prompt"] == "v1 prompt"

        with pytest.raises(ValueError, match="[Vv]ersion"):
            evolver.rollback("my_agent", version=999)

        store.close()
