"""MCP Client — connects to MCP servers and discovers/calls tools."""

from __future__ import annotations

import itertools
import threading
from typing import Any, Dict, List

from vortis.mcp.protocol import MCPError, MCPRequest, MCPResponse
from vortis.mcp.transport import MCPTransport
from vortis.tools._stubs import ToolSpec


class MCPClient:
    """Client that communicates with an MCP server via a transport.

    Parameters
    ----------
    transport:
        The transport layer to use for communication.
    """

    def __init__(self, transport: MCPTransport) -> None:
        self._transport = transport
        self._initialized = False
        self._capabilities: Dict[str, Any] = {}
        self._id_counter = itertools.count(1)
        self._request_lock = threading.RLock()
        self._closed = threading.Event()
        self._transport_closed = threading.Event()
        self._close_lock = threading.Lock()

    def _next_id(self) -> int:
        return next(self._id_counter)

    def _send(self, method: str, params: Dict[str, Any] | None = None) -> MCPResponse:
        """Send a request and check for errors."""
        with self._request_lock:
            self._raise_if_closed()
            request = MCPRequest(
                method=method,
                params=params or {},
                id=self._next_id(),
            )
            response = self._transport.send(request)
        if response.error is not None:
            raise MCPError(
                code=response.error.get("code", -1),
                message=response.error.get("message", "Unknown error"),
                data=response.error.get("data"),
            )
        return response

    def _raise_if_closed(self) -> None:
        if self._closed.is_set():
            raise RuntimeError("MCP client is closed")

    def initialize(self) -> Dict[str, Any]:
        """Perform the MCP initialize handshake.

        Sends the required client info and protocol version, then
        confirms with a ``notifications/initialized`` notification
        as required by the MCP specification.

        Returns the server capabilities.
        """
        params = {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "vortis", "version": "0.1.0"},
        }
        response = self._send("initialize", params)
        self._initialized = True
        self._capabilities = response.result.get("capabilities", {})
        self.notify("notifications/initialized")
        return response.result

    def notify(self, method: str, params: Dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification (no response expected).

        Per JSON-RPC 2.0 spec, notifications omit the ``id`` field entirely.
        """
        request = MCPRequest(
            method=method,
            params=params or {},
            id=None,
        )
        with self._request_lock:
            self._raise_if_closed()
            self._transport.send_notification(request)

    def list_tools(self) -> List[ToolSpec]:
        """Discover available tools from the server.

        Returns a list of ``ToolSpec`` objects.
        """
        response = self._send("tools/list")
        tools = response.result.get("tools", [])
        return [
            ToolSpec(
                name=t["name"],
                description=t.get("description", ""),
                parameters=t.get("inputSchema", {}),
                timeout_seconds=600.0,
            )
            for t in tools
        ]

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Call a tool on the server.

        Returns the result dictionary with ``content`` and ``isError`` fields.
        """
        response = self._send(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        return response.result

    def close(self) -> None:
        """Close the transport connection."""
        with self._close_lock:
            if self._transport_closed.is_set():
                return
            self._closed.set()
            self._transport.close()
            self._transport_closed.set()

    def __enter__(self) -> MCPClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


__all__ = ["MCPClient"]
