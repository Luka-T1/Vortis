"""``show_on_screen``: put text or a chart on the TV / phone / PC right now."""

from __future__ import annotations

import json
from typing import Any

from vortis.core.registry import ToolRegistry
from vortis.core.types import ToolResult
from vortis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("show_on_screen")
class ShowOnScreenTool(BaseTool):
    tool_id = "show_on_screen"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="show_on_screen",
            description=(
                "Show something on the user's screen immediately: a chart of "
                "numbers you computed, a table or notes in Markdown. Use it "
                "whenever the user says 'show me', 'give me a chart/graph', "
                "'put it on the TV'. Compute numbers with code first; never "
                "invent data."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "markdown": {
                        "type": "string",
                        "description": "Text, table or code to show (Markdown).",
                    },
                    "chart": {
                        "type": "object",
                        "description": (
                            "Optional chart: {type: line|bar|area|scatter|pie, "
                            "x: [labels], series: [{name, values: [numbers]}], "
                            "x_label, y_label}"
                        ),
                    },
                    "target": {
                        "type": "string",
                        "enum": ["all", "tv", "phone", "pc"],
                        "description": "Which screen; 'all' if unsure.",
                    },
                },
                "required": ["title"],
            },
            category="display",
            timeout_seconds=10,
        )

    def execute(self, **params: Any) -> ToolResult:
        from vortis.display import DisplayError, push

        chart = params.get("chart")
        if isinstance(chart, str) and chart.strip():
            try:
                chart = json.loads(chart)
            except ValueError:
                return ToolResult(
                    tool_name="show_on_screen",
                    content="chart must be a JSON object",
                    success=False,
                )
        try:
            item = push(
                title=str(params.get("title", "")),
                markdown=str(params.get("markdown", "") or ""),
                chart=chart or None,
                target=str(params.get("target", "all") or "all"),
                source="assistant",
            )
        except DisplayError as exc:
            return ToolResult(
                tool_name="show_on_screen", content=str(exc), success=False
            )
        return ToolResult(
            tool_name="show_on_screen",
            content=(
                f"Sent to screen '{item['target']}' (id {item['id']}). Whether a "
                "screen is open to show it was not verified."
            ),
            metadata={"outcome": "unverified", "display_id": item["id"]},
        )
