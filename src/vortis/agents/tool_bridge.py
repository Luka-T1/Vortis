"""Loopback MCP endpoint that lets an external agent call Vortis tools.

The bridge speaks the JSON flavour of MCP Streamable HTTP on ``127.0.0.1``
with a random bearer token, and dispatches every call through the owning
agent's :class:`ToolExecutor`, so capability policy, rate limits, taint
tracking and confirmations apply exactly as they do for local agents.
"""

from __future__ import annotations

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional

from vortis.core.types import ToolCall, ToolResult

SUPPORTED_PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_BODY = 4 * 1024 * 1024


class ToolBridge:
    """Serve ``tools`` over MCP on a loopback port until :meth:`close`."""

    def __init__(
        self,
        tools: List[Any],
        execute: Callable[[ToolCall], ToolResult],
    ) -> None:
        self._tools = {t.spec.name: t for t in tools}
        self._execute = execute
        self.token = secrets.token_urlsafe(32)
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        self.start()
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}/mcp"

    def start(self) -> None:
        with self._lock:
            if self._server is not None:
                return
            bridge = self

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args: Any) -> None:
                    return

                def do_GET(self) -> None:
                    self.send_response(405)
                    self.send_header("Allow", "POST")
                    self.end_headers()

                def do_DELETE(self) -> None:
                    self.send_response(204)
                    self.end_headers()

                def do_POST(self) -> None:
                    bridge._serve(self)

            self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            self._server.daemon_threads = True
            self._thread = threading.Thread(
                target=self._server.serve_forever,
                name="vortis-tool-bridge",
                daemon=True,
            )
            self._thread.start()

    def close(self) -> None:
        with self._lock:
            server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()

    def _authorized(self, header: str) -> bool:
        expected = f"Bearer {self.token}"
        return hmac.compare_digest(header.encode(), expected.encode())

    def _serve(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._authorized(handler.headers.get("Authorization", "")):
            self._reply(handler, 401, {"error": "unauthorized"})
            return
        try:
            length = int(handler.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._reply(handler, 413, {"error": "payload too large"})
            return
        try:
            payload = json.loads(handler.rfile.read(length) or b"null")
        except ValueError:
            self._reply(handler, 400, _error(None, -32700, "Parse error"))
            return

        batch = payload if isinstance(payload, list) else [payload]
        replies = [r for r in (self.dispatch(m) for m in batch) if r is not None]
        if not replies:
            handler.send_response(202)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        self._reply(handler, 200, replies if isinstance(payload, list) else replies[0])

    @staticmethod
    def _reply(handler: BaseHTTPRequestHandler, status: int, body: Any) -> None:
        data = json.dumps(body).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    def dispatch(self, message: Any) -> Optional[Dict[str, Any]]:
        """Answer one JSON-RPC message; notifications return ``None``."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "Invalid request")
        method = message.get("method")
        if "id" not in message:
            return None
        req_id = message["id"]
        params = message.get("params") or {}
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = (
                requested
                if requested in SUPPORTED_PROTOCOLS
                else SUPPORTED_PROTOCOLS[0]
            )
            return _result(
                req_id,
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "vortis", "version": "1.0.0"},
                },
            )
        if method == "ping":
            return _result(req_id, {})
        if method == "tools/list":
            return _result(
                req_id,
                {
                    "tools": [
                        {
                            "name": t.spec.name,
                            "description": t.spec.description,
                            "inputSchema": t.spec.parameters or {"type": "object"},
                        }
                        for t in self._tools.values()
                    ]
                },
            )
        if method == "tools/call":
            return self._call(req_id, params)
        return _error(req_id, -32601, f"Unknown method: {method}")

    def _call(self, req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        if name not in self._tools:
            return _error(req_id, -32602, f"Unknown tool: {name}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _error(req_id, -32602, "arguments must be an object")
        call = ToolCall(
            id=f"bridge-{secrets.token_hex(6)}",
            name=name,
            arguments=json.dumps(arguments),
        )
        try:
            result = self._execute(call)
        except Exception as exc:
            result = ToolResult(
                tool_name=name, content=f"Tool failed: {exc}", success=False
            )
        return _result(
            req_id,
            {
                "content": [{"type": "text", "text": result.content or ""}],
                "isError": not result.success,
            },
        )


def _result(req_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


__all__ = ["ToolBridge"]
