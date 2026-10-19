"""Tests for the Ollama engine backend."""

from __future__ import annotations

import json

import httpx
import pytest

try:
    import respx

    _HAS_RESPX = True
except ImportError:
    respx = None  # type: ignore[assignment]  # pins below run without it.
    _HAS_RESPX = False

from vortis.core.registry import EngineRegistry
from vortis.core.types import Message, Role
from vortis.engine._base import EngineConnectionError
from vortis.engine.ollama import OllamaEngine, _is_control_token_only_args

requires_respx = pytest.mark.skipif(
    not _HAS_RESPX, reason="respx not installed (optional test-only dependency)"
)


@pytest.fixture()
def engine() -> OllamaEngine:
    EngineRegistry.register_value("ollama", OllamaEngine)
    return OllamaEngine(host="http://testhost:11434")


@requires_respx
class TestOllamaGenerate:
    def test_generate_returns_content(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {"role": "assistant", "content": "Hello!"},
                        "model": "qwen3:8b",
                        "prompt_eval_count": 10,
                        "eval_count": 5,
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            )
        assert result["content"] == "Hello!"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5
        assert result["usage"]["total_tokens"] == 15

    def test_generate_connection_error(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
                )


@requires_respx
class TestOllamaListModels:
    def test_list_models(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:11434/api/tags").mock(
                return_value=httpx.Response(
                    200,
                    json={"models": [{"name": "qwen3:8b"}, {"name": "llama3.2:3b"}]},
                )
            )
            models = engine.list_models()
        assert models == ["qwen3:8b", "llama3.2:3b"]


@requires_respx
class TestOllamaHealth:
    def test_health_true(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:11434/api/tags").mock(
                return_value=httpx.Response(200, json={"models": []})
            )
            assert engine.health() is True

    def test_health_false(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:11434/api/tags").mock(
                side_effect=httpx.ConnectError("refused")
            )
            assert engine.health() is False


class TestControlTokenFilter:
    """Qwen3 ``/think`` / ``/no_think`` soft-switch tokens sometimes leak into
    tool-call arguments on small models (e.g. ``{"command": "/no_think"}``).
    Such a call is never valid and must be dropped before execution.
    """

    @pytest.mark.parametrize(
        "raw_args",
        [
            {"command": "/no_think"},
            {"command": "/think"},
            {"command": "  /no_think  "},
            {"command": "/NO_THINK"},
            "/no_think",
            json.dumps({"command": "/no_think"}),
            {"command": "/no_think", "note": ""},
        ],
    )
    def test_detects_control_token_only(self, raw_args) -> None:
        assert _is_control_token_only_args(raw_args) is True

    @pytest.mark.parametrize(
        "raw_args",
        [
            {"command": "date"},
            {"command": "echo /no_think"},
            {"query": "what is /no_think"},
            {"command": "date", "note": "/no_think"},
            {"timeout": 30},
            {},
            "date",
            "not json at all",
        ],
    )
    def test_keeps_legitimate_args(self, raw_args) -> None:
        assert _is_control_token_only_args(raw_args) is False


@requires_respx
class TestOllamaGenerateControlToken:
    def test_generate_drops_control_token_tool_call(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "shell_exec",
                                        "arguments": {"command": "/no_think"},
                                    }
                                }
                            ],
                        },
                        "model": "qwen3:14b",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="run date")],
                model="qwen3:14b",
                tools=[{"type": "function", "function": {"name": "shell_exec"}}],
            )
        assert not result.get("tool_calls")

    def test_generate_keeps_valid_tool_call(self, engine: OllamaEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "shell_exec",
                                        "arguments": {"command": "date"},
                                    }
                                }
                            ],
                        },
                        "model": "qwen3:14b",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="run date")],
                model="qwen3:14b",
                tools=[{"type": "function", "function": {"name": "shell_exec"}}],
            )
        assert len(result["tool_calls"]) == 1
        assert json.loads(result["tool_calls"][0]["arguments"]) == {"command": "date"}

    def test_generate_drops_only_control_token_among_many(
        self, engine: OllamaEngine
    ) -> None:
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "shell_exec",
                                        "arguments": {"command": "/no_think"},
                                    }
                                },
                                {
                                    "function": {
                                        "name": "shell_exec",
                                        "arguments": {"command": "date"},
                                    }
                                },
                            ],
                        },
                        "model": "qwen3:14b",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="run date")],
                model="qwen3:14b",
                tools=[{"type": "function", "function": {"name": "shell_exec"}}],
            )
        assert len(result["tool_calls"]) == 1
        assert json.loads(result["tool_calls"][0]["arguments"]) == {"command": "date"}


@requires_respx
class TestOllamaStreamFullControlToken:
    @pytest.mark.asyncio
    async def test_stream_full_drops_control_token_tool_call(
        self, engine: OllamaEngine
    ) -> None:
        lines = [
            json.dumps(
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "shell_exec",
                                    "arguments": {"command": "/no_think"},
                                }
                            }
                        ],
                    },
                    "done": True,
                }
            ),
        ]
        body = "\n".join(lines)
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(200, text=body)
            )
            chunks = []
            async for chunk in engine.stream_full(
                [Message(role=Role.USER, content="run date")],
                model="qwen3:14b",
                tools=[{"type": "function", "function": {"name": "shell_exec"}}],
            ):
                chunks.append(chunk)
        assert all(not c.tool_calls for c in chunks)


@requires_respx
class TestOllamaStream:
    @pytest.mark.asyncio
    async def test_stream_yields_content(self, engine: OllamaEngine) -> None:
        lines = [
            json.dumps({"message": {"content": "Hello"}, "done": False}),
            json.dumps({"message": {"content": " world"}, "done": True}),
        ]
        body = "\n".join(lines)
        with respx.mock:
            respx.post("http://testhost:11434/api/chat").mock(
                return_value=httpx.Response(200, text=body)
            )
            tokens = []
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            ):
                tokens.append(tok)
        assert "Hello" in tokens


def _ndjson_transport(lines: list[str]) -> httpx.MockTransport:
    body = "\n".join(lines) + "\n"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    return httpx.MockTransport(handler)


class TestOllamaStreamIsAsyncAndBounded:
    """Regression pins: the Ollama stream paths are async (never iterate the SYNC
    httpx client between tokens, which blocked the single uvicorn worker on every
    inter-token wait) and a mid-stream disconnect is bounded and mapped to a clean
    error. Uses httpx.MockTransport directly, so it runs without respx."""

    @pytest.mark.asyncio
    async def test_stream_does_not_use_blocking_sync_client(self) -> None:
        engine = OllamaEngine(host="http://localhost:11434")
        engine._async_transport = _ndjson_transport(
            [
                json.dumps({"message": {"content": "Hi"}, "done": False}),
                json.dumps({"message": {"content": " there"}, "done": True}),
            ]
        )

        class _Boom:
            def stream(self, *a, **k):  # pragma: no cover - must never run
                raise AssertionError("streaming used the blocking sync client")

        engine._client = _Boom()  # type: ignore[assignment]
        tokens = [
            tok
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            )
        ]
        assert tokens == ["Hi", " there"]

    @pytest.mark.asyncio
    async def test_stream_full_does_not_use_blocking_sync_client(self) -> None:
        engine = OllamaEngine(host="http://localhost:11434")
        engine._async_transport = _ndjson_transport(
            [
                json.dumps({"message": {"content": "Hi"}, "done": False}),
                json.dumps(
                    {"message": {"content": "", "tool_calls": []}, "done": True}
                ),
            ]
        )

        class _Boom:
            def stream(self, *a, **k):  # pragma: no cover - must never run
                raise AssertionError("stream_full used the blocking sync client")

        engine._client = _Boom()  # type: ignore[assignment]
        chunks = [
            c
            async for c in engine.stream_full(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            )
        ]
        assert any(c.content == "Hi" for c in chunks)

    @pytest.mark.asyncio
    async def test_timeout_is_applied_to_async_stream_client(self) -> None:
        engine = OllamaEngine(host="http://localhost:11434", timeout=0.05)
        assert engine._timeout == 0.05
        client = engine._make_async_client()
        try:
            assert client.timeout == httpx.Timeout(0.05)
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_mid_stream_disconnect_maps_to_connection_error(self) -> None:
        class _MidStreamCrashStream(httpx.AsyncByteStream):
            def __init__(self, request: httpx.Request) -> None:
                self._request = request

            async def __aiter__(self):
                yield b'{"message": {"content": "Hi"}, "done": false}\n'
                raise httpx.RemoteProtocolError(
                    "peer closed connection mid-stream", request=self._request
                )

            async def aclose(self) -> None:  # pragma: no cover - trivial
                pass

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=_MidStreamCrashStream(request))

        engine = OllamaEngine(host="http://localhost:11434")
        engine._async_transport = httpx.MockTransport(handler)
        tokens: list[str] = []
        with pytest.raises(EngineConnectionError):
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            ):
                tokens.append(tok)
        assert tokens == ["Hi"]


class TestOllamaStreamHttpErrorMapping:
    """Regression pins: Ollama streaming non-2xx responses map to the same
    ``EngineConnectionError`` as the OpenAI-compat engine (via
    ``_raise_stream_http_error``), instead of leaking a raw
    ``httpx.HTTPStatusError`` from ``raise_for_status()``. A 3xx must NOT fall
    through to a silent empty stream. Uses ``httpx.MockTransport`` directly, so
    it runs without respx."""

    @staticmethod
    def _status_transport(
        status: int, *, text: str = "", headers: dict | None = None
    ) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, text=text, headers=headers or {})

        return httpx.MockTransport(handler)

    @pytest.mark.asyncio
    async def test_stream_500_maps_to_connection_error(self) -> None:
        engine = OllamaEngine(host="http://localhost:11434")
        engine._async_transport = self._status_transport(500, text="internal boom")
        tokens: list[str] = []
        with pytest.raises(EngineConnectionError) as excinfo:
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            ):
                tokens.append(tok)
        assert not isinstance(excinfo.value, httpx.HTTPStatusError)
        assert "500" in str(excinfo.value)
        assert "internal boom" in str(excinfo.value)
        assert tokens == []

    @pytest.mark.asyncio
    async def test_stream_full_500_maps_to_connection_error(self) -> None:
        engine = OllamaEngine(host="http://localhost:11434")
        engine._async_transport = self._status_transport(500, text="internal boom")
        with pytest.raises(EngineConnectionError) as excinfo:
            async for _ in engine.stream_full(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            ):
                pass
        assert not isinstance(excinfo.value, httpx.HTTPStatusError)
        assert "500" in str(excinfo.value)
        assert "internal boom" in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_stream_3xx_maps_to_connection_error_not_silent(self) -> None:
        engine = OllamaEngine(host="http://localhost:11434")
        engine._async_transport = self._status_transport(
            302, headers={"location": "http://elsewhere/api/chat"}
        )
        tokens: list[str] = []
        with pytest.raises(EngineConnectionError) as excinfo:
            async for tok in engine.stream(
                [Message(role=Role.USER, content="Hi")], model="qwen3:8b"
            ):
                tokens.append(tok)
        assert "302" in str(excinfo.value)
        assert tokens == []

    @pytest.mark.asyncio
    async def test_400_tools_retry_still_fires(self) -> None:
        calls: list[bool] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            had_tools = "tools" in payload
            calls.append(had_tools)
            if had_tools:
                return httpx.Response(400, text="model does not support tools")
            body = (
                json.dumps({"message": {"content": "recovered"}, "done": True}) + "\n"
            )
            return httpx.Response(200, text=body)

        engine = OllamaEngine(host="http://localhost:11434")
        engine._async_transport = httpx.MockTransport(handler)
        chunks = [
            c
            async for c in engine.stream_full(
                [Message(role=Role.USER, content="Hi")],
                model="qwen3:8b",
                tools=[{"type": "function", "function": {"name": "shell_exec"}}],
            )
        ]
        assert calls == [True, False]
        assert any(c.content == "recovered" for c in chunks)
