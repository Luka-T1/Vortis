"""SkillTool — wraps a skill as a tool that agents can invoke."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from vortis.core.types import ToolResult
from vortis.skills.executor import SkillExecutor
from vortis.skills.types import SkillManifest
from vortis.tools._stubs import BaseTool, ToolSpec

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


class SkillTool(BaseTool):
    """Wraps a SkillManifest as a BaseTool that agents can invoke.

    Follows the same adapter pattern as MCPToolAdapter.

    Parameters
    ----------
    manifest:
        The skill manifest to wrap.
    executor:
        A :class:`SkillExecutor` used to run the skill pipeline.
    skill_manager:
        Optional skill manager (reserved for sub-skill delegation).
    """

    tool_id: str

    def __init__(
        self,
        manifest: SkillManifest,
        executor: SkillExecutor,
        *,
        skill_manager: Optional[Any] = None,
    ) -> None:
        self._manifest = manifest
        self._executor = executor
        self._skill_manager = skill_manager
        self.tool_id = f"skill_{manifest.name}"
        self._parameters = self._build_parameters()


    def _build_parameters(self) -> Dict[str, Any]:
        """Auto-extract input parameters from the manifest.

        For pipeline skills, scan each step's ``arguments_template`` for
        ``{placeholder}`` patterns.  Subtract the ``output_key`` values
        produced by *prior* steps so only externally-supplied parameters
        are exposed.

        For instruction-only skills (no steps), expose a single optional
        ``task`` parameter.
        """
        if not self._manifest.steps:
            return {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Optional task description or context.",
                    }
                },
            }

        produced: Set[str] = set()
        input_params: List[str] = []
        seen: Set[str] = set()

        for step in self._manifest.steps:
            placeholders = _PLACEHOLDER_RE.findall(step.arguments_template)
            for ph in placeholders:
                if ph not in produced and ph not in seen:
                    input_params.append(ph)
                    seen.add(ph)

            if step.output_key:
                produced.add(step.output_key)

        properties: Dict[str, Any] = {}
        for param in input_params:
            properties[param] = {
                "type": "string",
                "description": f"Input value for '{param}'.",
            }

        return {
            "type": "object",
            "properties": properties,
        }


    def _build_result_metadata(self, *, steps_run: int) -> Dict[str, Any]:
        """Build the metadata dict attached to ToolResult.

        Includes the skill name, source provenance, and kind so downstream
        consumers (TraceCollector, SkillOptimizer) can bucket invocations.
        """
        vortis_meta = self._manifest.metadata.get("vortis", {}) or {}
        source = vortis_meta.get("source", "user")
        kind = "executable" if self._manifest.steps else "instructional"
        return {
            "skill": self._manifest.name,
            "skill_source": source,
            "skill_kind": kind,
            "steps": steps_run,
        }


    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=f"skill_{self._manifest.name}",
            description=self._manifest.description or f"Skill: {self._manifest.name}",
            parameters=self._parameters,
            category="skill",
            required_capabilities=self._manifest.required_capabilities,
        )

    def execute(self, **params: Any) -> ToolResult:
        """Execute the skill.

        If the manifest has pipeline steps, run them via the executor and
        collect the last step's output.  If ``markdown_content`` is present,
        append it to the content.  Returns a combined :class:`ToolResult`.
        """
        tool_name = self.spec.name
        content_parts: List[str] = []

        if self._manifest.steps:
            initial_ctx: Dict[str, Any] = {k: v for k, v in params.items()}

            result = self._executor.run(self._manifest, initial_context=initial_ctx)

            if not result.success:
                error_content = (
                    result.step_results[-1].content
                    if result.step_results
                    else "Pipeline failed with no step results."
                )
                return ToolResult(
                    tool_name=tool_name,
                    content=error_content,
                    success=False,
                    metadata=self._build_result_metadata(
                        steps_run=len(result.step_results)
                    ),
                )

            if result.step_results:
                last_step = result.step_results[-1]
                last_output = (
                    result.context.get(
                        self._manifest.steps[-1].output_key,
                        last_step.content,
                    )
                    if self._manifest.steps[-1].output_key
                    else last_step.content
                )
                content_parts.append(str(last_output))

        if self._manifest.markdown_content:
            content_parts.append(self._manifest.markdown_content)

        combined = "\n\n".join(filter(None, content_parts))

        return ToolResult(
            tool_name=tool_name,
            content=combined,
            success=True,
            metadata=self._build_result_metadata(steps_run=len(self._manifest.steps)),
        )


__all__ = ["SkillTool"]
