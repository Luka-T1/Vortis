"""Register daemon state only after Uvicorn has opened its listening socket."""

from __future__ import annotations

import os
import socket
from typing import Any

import uvicorn

from vortis.cli.daemon_cmd import clear_server_state, record_server_state


class DaemonServer(uvicorn.Server):
    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if not self.started:
            return
        listener = next(
            sock for server in self.servers for sock in (server.sockets or [])
        )
        host, port = listener.getsockname()[:2]
        try:
            record_server_state(os.getpid(), host, port)
        except Exception:
            await self.shutdown(sockets=sockets)
            raise


def run_server(app: Any, *, host: str, port: int, log_level: str = "info") -> None:
    server = DaemonServer(
        uvicorn.Config(app, host=host, port=port, log_level=log_level)
    )
    try:
        server.run()
    finally:
        clear_server_state(os.getpid())
