"""Tests for the Claude account agent and its loopback tool bridge."""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from vortis.agents._stubs import AgentContext, AgentResult
from vortis.agents.claude_account import ClaudeAccountAgent, compose_prompt
from vortis.agents.claude_code import _RUNNER_SRC
from vortis.agents.tool_bridge import ToolBridge
from vortis.core.config import ClaudeConfig
from vortis.core.registry import AgentRegistry
from vortis.core.types import Message, Role, ToolResult
from vortis.tools._stubs import BaseTool, ToolSpec

FAKE_SDK = Path(__file__).with_name("fake_claude_sdk.mjs")


class EchoTool(BaseTool):
    tool_id = "echo"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="echo",
            description="Echo text back.",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}},
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(tool_name="echo", content=f"echo:{params.get('text', '')}")


def _post(bridge: ToolBridge, body, token: str | None = None):
    req = urllib.request.Request(
        bridge.url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token or bridge.token}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as res:
        raw = res.read()
        return res.status, (json.loads(raw) if raw else None)


@pytest.fixture
def bridge():
    agent = ClaudeAccountAgent(
        MagicMock(), "local", tools=[EchoTool()], settings=ClaudeConfig()
    )
    instance = ToolBridge(agent._tools, agent._executor.execute)
    yield instance
    instance.close()


class TestToolBridge:
    def test_lists_and_calls_tools(self, bridge):
        status, init = _post(
            bridge,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
        )
        assert status == 200
        assert init["result"]["protocolVersion"] == "2025-06-18"

        _, listed = _post(bridge, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert [t["name"] for t in listed["result"]["tools"]] == ["echo"]

        _, called = _post(
            bridge,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "x"}},
            },
        )
        assert called["result"] == {
            "content": [{"type": "text", "text": "echo:x"}],
            "isError": False,
        }

    def test_notifications_are_accepted_without_body(self, bridge):
        status, body = _post(
            bridge, {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert status == 202
        assert body is None

    def test_rejects_wrong_token(self, bridge):
        with pytest.raises(urllib.error.HTTPError) as err:
            _post(
                bridge,
                {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                token="nope",
            )
        assert err.value.code == 401

    def test_unknown_tool_and_method(self, bridge):
        _, unknown = _post(
            bridge,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "rm", "arguments": {}},
            },
        )
        assert unknown["error"]["code"] == -32602
        _, missing = _post(
            bridge, {"jsonrpc": "2.0", "id": 2, "method": "resources/list"}
        )
        assert missing["error"]["code"] == -32601

    def test_binds_to_loopback(self, bridge):
        assert bridge.url.startswith("http://127.0.0.1:")


class TestComposePrompt:
    def test_single_message_is_passed_through(self):
        assert (
            compose_prompt([Message(role=Role.USER, content="Koliko je 2+2?")])
            == "Koliko je 2+2?"
        )

    def test_history_is_folded_before_latest_request(self):
        prompt = compose_prompt(
            [
                Message(role=Role.USER, content="Simuliraj kosi hitac"),
                Message(role=Role.ASSISTANT, content="Otvorio sam simulaciju."),
                Message(role=Role.USER, content="A pod uglom od 60?"),
            ]
        )
        assert prompt.startswith("Earlier in this conversation:")
        assert "User: Simuliraj kosi hitac" in prompt
        assert "Assistant: Otvorio sam simulaciju." in prompt
        assert prompt.endswith("Current request:\nA pod uglom od 60?")


@pytest.fixture(autouse=True)
def _simple_agent():
    from vortis.agents.simple import SimpleAgent

    AgentRegistry.register_value("simple", SimpleAgent)


def _agent(**settings) -> ClaudeAccountAgent:
    engine = MagicMock()
    engine.engine_id = "mock"
    return ClaudeAccountAgent(
        engine,
        "qwen3.5:2b",
        tools=[EchoTool()],
        settings=ClaudeConfig(**settings),
    )


def _proc(payload: dict, returncode: int = 0):
    stdout = (
        f"---VORTIS_OUTPUT_START---\n{json.dumps(payload)}\n---VORTIS_OUTPUT_END---\n"
    )
    return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


class TestClaudeAccountAgent:
    def test_is_registered_and_accepts_tools(self):
        AgentRegistry.register_value("claude_account", ClaudeAccountAgent)
        assert AgentRegistry.get("claude_account") is ClaudeAccountAgent
        assert ClaudeAccountAgent.accepts_tools is True

    def test_sends_model_system_prompt_and_bridge(self):
        agent = _agent(model="opus", web=False)
        ctx = AgentContext()
        ctx.conversation.add(Message(role=Role.SYSTEM, content="Ti si Jarvis."))
        with (
            patch(
                "vortis.agents.claude_account.ensure_runner",
                return_value=("node", Path(".")),
            ),
            patch("vortis.agents.claude_account.subprocess.run") as run,
        ):
            run.return_value = _proc(
                {"content": "Četiri.", "tool_results": [], "metadata": {"turns": 1}}
            )
            result = agent.run("Koliko je 2+2?", context=ctx)
        agent.close()

        request = json.loads(run.call_args.kwargs["input"])
        assert run.call_args.args[0] == ["node", "account.mjs"]
        assert request["model"] == "opus"
        assert request["web"] is False
        assert request["prompt"] == "Koliko je 2+2?"
        assert "Ti si Jarvis." in request["system_prompt"]
        assert "simulate" in request["system_prompt"]
        assert request["mcp"]["url"].startswith("http://127.0.0.1:")
        assert request["mcp"]["token"]
        assert result.content == "Četiri."
        assert result.metadata["engine"] == "claude_account"

    def test_falls_back_to_local_agent_and_backs_off(self):
        agent = _agent(fallback_agent="simple")
        fallback = MagicMock()
        fallback.run.side_effect = lambda *a, **k: AgentResult(
            content="lokalno", turns=1
        )
        agent._fallback = fallback
        with (
            patch(
                "vortis.agents.claude_account.ensure_runner",
                return_value=("node", Path(".")),
            ),
            patch("vortis.agents.claude_account.subprocess.run") as run,
        ):
            run.return_value = _proc(
                {
                    "content": "Not logged in · Please run /login",
                    "tool_results": [],
                    "metadata": {"error": True, "auth_error": True},
                },
                returncode=1,
            )
            first = agent.run("zdravo")
            second = agent.run("opet")
        agent.close()

        assert first.content == "lokalno"
        assert first.metadata["fallback"] == "simple"
        assert "login" in first.metadata["fallback_reason"]
        assert run.call_count == 1
        assert second.content == "lokalno"
        assert fallback._model == "qwen3.5:2b"

    def test_missing_node_uses_fallback(self):
        agent = _agent(fallback_agent="simple")
        agent._fallback = MagicMock(
            run=MagicMock(return_value=AgentResult(content="ok"))
        )
        with patch(
            "vortis.agents.claude_account.ensure_runner",
            side_effect=RuntimeError("ClaudeCodeAgent requires Node.js (>=22)."),
        ):
            result = agent.run("zdravo")
        assert result.content == "ok"
        assert "Node.js" in result.metadata["fallback_reason"]

    def test_reports_error_without_fallback(self):
        agent = _agent(fallback_agent="")
        with patch(
            "vortis.agents.claude_account.ensure_runner",
            side_effect=RuntimeError("no node"),
        ):
            result = agent.run("zdravo")
        assert result.metadata["error"] is True
        assert "no node" in result.content

    def test_builds_registered_fallback_with_shared_tools(self):
        agent = _agent(fallback_agent="simple")
        fallback = agent._fallback_agent()
        assert fallback is not None
        assert fallback.agent_id == "simple"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
class TestAccountRunner:
    def _runner(self, tmp_path: Path) -> Path:
        shutil.copy2(_RUNNER_SRC / "account.mjs", tmp_path / "account.mjs")
        sdk = tmp_path / "node_modules" / "@anthropic-ai" / "claude-agent-sdk"
        sdk.mkdir(parents=True)
        (sdk / "package.json").write_text(
            '{"name":"@anthropic-ai/claude-agent-sdk","version":"0.3.237","type":"module","main":"index.js"}'
        )
        shutil.copy2(FAKE_SDK, sdk / "index.js")
        return tmp_path

    def test_runs_tools_through_bridge(self, tmp_path, monkeypatch):
        runner = self._runner(tmp_path)
        record = tmp_path / "record.json"
        monkeypatch.setenv("FAKE_SDK_RECORD", str(record))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-used")
        agent = _agent(model="opus")
        with patch(
            "vortis.agents.claude_account.ensure_runner",
            return_value=(shutil.which("node"), runner),
        ):
            result = agent.run("Pozdravi")
        agent.close()

        assert result.content == "Gotovo."
        assert result.metadata["model"] == "opus"
        assert result.metadata["total_tokens"] == 14
        assert [(t.tool_name, t.content, t.success) for t in result.tool_results] == [
            ("echo", "echo:hi", True)
        ]
        seen = json.loads(record.read_text())
        assert "ANTHROPIC_API_KEY" not in seen["env"]
        assert seen["options"]["settingSources"] == []
        assert "Bash" in seen["options"]["disallowedTools"]
        assert seen["options"]["allowedTools"] == [
            "mcp__vortis",
            "WebSearch",
            "WebFetch",
        ]

    def test_marks_login_errors(self, tmp_path, monkeypatch):
        runner = self._runner(tmp_path)
        monkeypatch.setenv("FAKE_SDK_FAIL", "Not logged in · Please run /login")
        agent = _agent(fallback_agent="")
        with patch(
            "vortis.agents.claude_account.ensure_runner",
            return_value=(shutil.which("node"), runner),
        ):
            result = agent.run("zdravo")
        assert result.metadata["error"] is True
        assert "login" in result.content
        assert agent._unavailable_until > 0
