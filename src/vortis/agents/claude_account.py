"""Claude through the user's own signed-in Claude account.

Runs the Claude Agent SDK with the account the Claude Code CLI is logged in
with, so no API key is needed. Vortis tools are offered to Claude through a
loopback MCP bridge and still run through this agent's ``ToolExecutor``.
When Claude cannot be reached the request is answered by a local fallback
agent on the configured engine, so Vortis keeps working offline.
"""

from __future__ import annotations

import inspect
import json
import logging
import subprocess
import threading
import time
from typing import Any, List, Optional

from vortis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from vortis.agents.claude_code import ClaudeCodeAgent, ensure_runner
from vortis.agents.tool_bridge import ToolBridge
from vortis.core.config import ClaudeConfig, load_config
from vortis.core.events import EventBus
from vortis.core.registry import AgentRegistry
from vortis.core.types import Role
from vortis.engine._stubs import InferenceEngine

logger = logging.getLogger(__name__)

TOOL_GUIDANCE = (
    "You run inside Vortis, the user's personal assistant, and reach the user's "
    "screens and devices only through the Vortis tools. Use them instead of "
    "estimating: calculator for arithmetic, simulate whenever the user asks to "
    "simulate, compare scenarios, see how one quantity depends on another or "
    "asks 'what if', and show_on_screen for charts, tables and longer material. "
    "Build simulations from correct equations with realistic default values and "
    "slider ranges, then explain the numbers the tool returns. Reply in the "
    "language of the user's message."
)
HISTORY_TURNS = 12
HISTORY_CHARS = 4000
AUTH_RETRY_SECONDS = 300
FAILURE_RETRY_SECONDS = 30


@AgentRegistry.register("claude_account")
class ClaudeAccountAgent(ToolUsingAgent):
    """Answer with Claude on the user's account, falling back to a local agent."""

    agent_id = "claude_account"

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        tools: Optional[List[Any]] = None,
        bus: Optional[EventBus] = None,
        max_turns: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        capability_policy: Optional[Any] = None,
        rate_limiter: Optional[Any] = None,
        agent_id: Optional[str] = None,
        prompt_builder: Optional[Any] = None,
        settings: Optional[ClaudeConfig] = None,
    ) -> None:
        super().__init__(
            engine,
            model,
            tools=tools,
            bus=bus,
            max_turns=max_turns,
            temperature=temperature,
            max_tokens=max_tokens,
            capability_policy=capability_policy,
            rate_limiter=rate_limiter,
            agent_id=agent_id,
            prompt_builder=prompt_builder,
        )
        if settings is None:
            try:
                settings = load_config().claude
            except Exception:
                settings = ClaudeConfig()
        self._settings = settings
        self._bridge: Optional[ToolBridge] = None
        self._fallback: Optional[Any] = None
        self._unavailable_until = 0.0
        self._lock = threading.Lock()

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        if time.monotonic() < self._unavailable_until:
            return self._run_fallback(
                input, context, "Claude is temporarily unavailable"
            )

        self._emit_turn_start(input)
        messages = self._build_messages(input, context)
        try:
            result = self._run_claude(messages)
        except Exception as exc:
            logger.warning("Claude account request failed: %s", exc)
            self._emit_turn_end(turns=1, error=True)
            self._unavailable_until = time.monotonic() + FAILURE_RETRY_SECONDS
            return self._run_fallback(input, context, str(exc))

        if result.metadata.get("error"):
            self._emit_turn_end(turns=result.turns, error=True)
            delay = (
                AUTH_RETRY_SECONDS
                if result.metadata.get("auth_error")
                else FAILURE_RETRY_SECONDS
            )
            self._unavailable_until = time.monotonic() + delay
            return self._run_fallback(input, context, result.content)

        self._emit_turn_end(turns=result.turns)
        return result

    def close(self) -> None:
        if self._bridge is not None:
            self._bridge.close()
            self._bridge = None

    def _tool_bridge(self) -> Optional[ToolBridge]:
        if not self._tools:
            return None
        with self._lock:
            if self._bridge is None:
                self._bridge = ToolBridge(self._tools, self._executor.execute)
                self._bridge.start()
            return self._bridge

    def _run_claude(self, messages: List[Any]) -> AgentResult:
        system_parts = [TOOL_GUIDANCE]
        system_parts.extend(
            m.text for m in messages if m.role == Role.SYSTEM and m.text
        )
        dialogue = [
            m for m in messages if m.role in (Role.USER, Role.ASSISTANT) and m.text
        ]
        request: dict[str, Any] = {
            "prompt": compose_prompt(dialogue),
            "system_prompt": "\n\n".join(system_parts),
            "model": self._settings.model,
            "max_turns": self._settings.max_turns,
            "web": self._settings.web,
        }
        bridge = self._tool_bridge()
        if bridge is not None:
            request["mcp"] = {"url": bridge.url, "token": bridge.token}

        node, runner_dir = ensure_runner()
        try:
            proc = subprocess.run(
                [node, "account.mjs"],
                cwd=str(runner_dir),
                input=json.dumps(request),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._settings.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Claude did not answer within {self._settings.timeout}s"
            ) from exc

        content, tool_results, metadata = ClaudeCodeAgent._parse_output(
            proc.stdout or ""
        )
        if proc.returncode != 0 and not metadata.get("error"):
            detail = (proc.stderr or content or "").strip()[-500:]
            raise RuntimeError(f"Claude runner exited with {proc.returncode}: {detail}")
        metadata["engine"] = "claude_account"
        return AgentResult(
            content=content,
            tool_results=tool_results,
            turns=int(metadata.get("turns") or 1),
            metadata=metadata,
        )

    def _run_fallback(
        self,
        input: str,
        context: Optional[AgentContext],
        reason: str,
    ) -> AgentResult:
        fallback = self._fallback_agent()
        if fallback is None:
            return AgentResult(
                content=f"Claude is not available: {reason}",
                turns=1,
                metadata={"error": True, "engine": "claude_account"},
            )
        fallback._model = self._model
        result = fallback.run(input, context=context)
        result.metadata["fallback"] = self._settings.fallback_agent
        result.metadata["fallback_reason"] = reason[:300]
        return result

    def _fallback_agent(self) -> Optional[Any]:
        name = self._settings.fallback_agent
        if not name or name == self.agent_id or not AgentRegistry.contains(name):
            return None
        with self._lock:
            if self._fallback is None:
                cls = AgentRegistry.get(name)
                candidates = {
                    "tools": self._tools,
                    "bus": self._bus,
                    "max_turns": self._max_turns,
                    "temperature": self._temperature,
                    "max_tokens": self._max_tokens,
                    "capability_policy": self._capability_policy,
                    "rate_limiter": self._rate_limiter,
                    "agent_id": self._runtime_agent_id,
                    "prompt_builder": self._prompt_builder,
                }
                accepted = inspect.signature(cls.__init__).parameters
                kwargs = {
                    key: value
                    for key, value in candidates.items()
                    if key in accepted and value is not None
                }
                self._fallback = cls(self._engine, self._model, **kwargs)
            return self._fallback


def compose_prompt(dialogue: List[Any]) -> str:
    """Fold earlier turns into one prompt that ends with the newest request."""
    if not dialogue:
        return ""
    *history, latest = dialogue[-HISTORY_TURNS:]
    if not history:
        return latest.text
    lines = ["Earlier in this conversation:"]
    for message in history:
        speaker = "User" if message.role == Role.USER else "Assistant"
        lines.append(f"{speaker}: {message.text[:HISTORY_CHARS]}")
    lines.append("")
    lines.append("Current request:")
    lines.append(latest.text)
    return "\n".join(lines)


__all__ = ["ClaudeAccountAgent", "compose_prompt"]
