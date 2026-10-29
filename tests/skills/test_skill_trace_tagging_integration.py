"""End-to-end integration test for skill trace tagging (Plan 2A C1 fix).

Verifies the full flow:
    SkillTool.execute()
        → ToolExecutor publishes TOOL_CALL_END with metadata
            → TraceCollector copies metadata into TraceStep.metadata
                → SkillOptimizer can bucket traces by skill name

If this test passes, the trace tagging path is wired end-to-end.
"""

from __future__ import annotations

import json

from vortis.core.events import EventBus
from vortis.core.types import StepType, ToolCall, ToolResult
from vortis.skills.executor import SkillExecutor
from vortis.skills.tool_adapter import SkillTool
from vortis.skills.types import SkillManifest
from vortis.tools._stubs import BaseTool, ToolExecutor, ToolSpec


class TestSkillTraceTaggingEndToEnd:
    def test_skill_metadata_flows_to_trace_step(self) -> None:
        """SkillTool metadata reaches TraceCollector via the event bus."""
        bus = EventBus(record_history=True)

        captured_metadata: dict = {}

        def _on_tool_end(event):
            nonlocal captured_metadata
            captured_metadata = event.data.get("metadata", {})

        from vortis.core.events import EventType

        bus.subscribe(EventType.TOOL_CALL_END, _on_tool_end)

        manifest = SkillManifest(
            name="research-skill",
            description="x",
            markdown_content="Just instructions.",
            metadata={"vortis": {"source": "hermes"}},
        )
        skill_executor = SkillExecutor(ToolExecutor([], bus=bus))
        skill_tool = SkillTool(manifest, skill_executor)

        tool_executor = ToolExecutor([skill_tool], bus=bus)
        tool_executor.execute(
            ToolCall(id="t1", name="skill_research-skill", arguments="{}")
        )

        assert captured_metadata.get("skill") == "research-skill"
        assert captured_metadata.get("skill_source") == "hermes"
        assert captured_metadata.get("skill_kind") == "instructional"

    def test_trace_collector_writes_metadata_to_step(self) -> None:
        """A real TraceCollector populates TraceStep.metadata from the event."""
        from vortis.traces.collector import TraceCollector

        bus = EventBus(record_history=True)

        manifest = SkillManifest(
            name="my-skill",
            description="x",
            markdown_content="Body",
            metadata={"vortis": {"source": "openclaw"}},
        )
        skill_executor = SkillExecutor(ToolExecutor([], bus=bus))
        skill_tool = SkillTool(manifest, skill_executor)
        tool_executor = ToolExecutor([skill_tool], bus=bus)

        class _StubAgent:
            agent_id = "stub"

            def run(self, query, context=None, **kwargs):
                from vortis.agents._stubs import AgentResult

                tool_executor.execute(
                    ToolCall(
                        id="t1",
                        name="skill_my-skill",
                        arguments="{}",
                    )
                )
                return AgentResult(content="done", turns=1)

        collector = TraceCollector(
            agent=_StubAgent(),
            store=None,
            bus=bus,
        )
        collector.run("test")

        trace = collector.last_trace
        assert trace is not None, "Collector should have captured a trace"

        tool_steps = [s for s in trace.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1, "Should have captured at least one tool step"

        first = tool_steps[0]
        assert first.metadata.get("skill") == "my-skill", (
            f"Expected metadata.skill='my-skill', got {first.metadata!r}"
        )
        assert first.metadata.get("skill_source") == "openclaw"
        assert first.metadata.get("skill_kind") == "instructional"


class _TaintingTool(BaseTool):
    """Test tool whose result triggers the auto_detect_taint codepath.

    Returns content containing strings the security taint scanner picks
    up as user-input or external — those add a `_taint: TaintSet` to
    the result metadata before TOOL_CALL_END is published.
    """

    tool_id = "tainting"

    @property
    def spec(self):
        return ToolSpec(name="tainting", description="emit tainted output")

    def execute(self, **params):
        return ToolResult(
            tool_name="tainting",
            content="user said: hello world",
            success=True,
        )


class TestEventMetadataIsJsonSafe:
    """Plan 2B regression: TOOL_CALL_END payload metadata must be JSON
    serializable so the trace store can persist it without crashing.

    Bug surfaced by Plan 2B Task 11 smoke test, where every PinchBench
    task failed with `Object of type TaintSet is not JSON serializable`
    because ToolExecutor was passing through the internal `_taint` key
    that the security auto-detect adds.
    """

    def test_event_metadata_excludes_non_json_objects(self):
        from vortis.core.events import EventType

        bus = EventBus(record_history=True)
        captured: dict = {}

        def _on_tool_end(event):
            nonlocal captured
            captured = dict(event.data.get("metadata") or {})

        bus.subscribe(EventType.TOOL_CALL_END, _on_tool_end)

        tool_executor = ToolExecutor([_TaintingTool()], bus=bus)
        tool_executor.execute(ToolCall(id="t1", name="tainting", arguments="{}"))

        try:
            json.dumps(captured)
        except (TypeError, ValueError) as exc:
            raise AssertionError(
                f"Published TOOL_CALL_END metadata is not JSON serializable: "
                f"{exc}.  Keys: {list(captured.keys())}"
            )

        assert "_taint" not in captured, (
            f"_taint key leaked into event metadata: {captured!r}"
        )

    def test_skill_metadata_still_present_after_filtering(self):
        """The JSON-safe filter must NOT drop legitimate skill metadata."""
        from vortis.core.events import EventType

        bus = EventBus(record_history=True)
        captured: dict = {}

        def _on_tool_end(event):
            nonlocal captured
            captured = dict(event.data.get("metadata") or {})

        bus.subscribe(EventType.TOOL_CALL_END, _on_tool_end)

        manifest = SkillManifest(
            name="my-skill",
            description="x",
            markdown_content="Body",
            metadata={"vortis": {"source": "hermes"}},
        )
        skill_executor = SkillExecutor(ToolExecutor([], bus=bus))
        skill_tool = SkillTool(manifest, skill_executor)

        tool_executor = ToolExecutor([skill_tool], bus=bus)
        tool_executor.execute(ToolCall(id="t1", name="skill_my-skill", arguments="{}"))

        assert captured.get("skill") == "my-skill"
        assert captured.get("skill_source") == "hermes"
        assert captured.get("skill_kind") == "instructional"

        json.dumps(captured)
