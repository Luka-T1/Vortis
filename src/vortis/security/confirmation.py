"""Human-only confirmation gate for risky tool calls.

Pattern adapted from FatihMakes/Mark-LVII ``core/confirm.py`` (the open-source
base of Torvis); this is an independent implementation, see NOTICE.

Why it exists
-------------
A tool spec can set ``requires_confirmation=True`` (shell, git commit, sending
messages, deleting files...). Before this module the server either refused
those tools outright (no TTY to ask on) or approved them with
``confirm_callback=lambda _prompt: True`` — i.e. the model approved itself.

Here the approval comes from the *interface*:

1. The tool executor calls :meth:`ConfirmationBroker.confirm`.
2. The broker publishes ``CONFIRMATION_REQUESTED`` on the event bus with a
   one-time token. The WebSocket bridge delivers it only to authenticated UI
   clients (HUD, chat, a paired phone).
3. The person presses CONFIRM / CANCEL; the UI posts the id *and* the token to
   ``/v1/confirmations/{id}``. The model never sees the token: it is not in
   any tool result, prompt or trace, and the model's own HTTP tool cannot reach
   loopback addresses (SSRF guard).
4. The executor thread that was waiting wakes up and runs (or skips) the tool.

No UI connected, or nobody answers within the timeout → the call is denied.
Denial is the safe default for something irreversible.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from vortis.core.events import EventBus, EventType

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 120.0
_MAX_PENDING = 32
_ARG_PREVIEW_CHARS = 600


@dataclass
class PendingConfirmation:
    id: str
    tool: str
    title: str
    detail: str
    arguments: Dict[str, Any]
    agent: str
    created_at: float
    expires_at: float
    token: str = field(repr=False)
    decision: Optional[bool] = None
    decided_by: str = ""
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self, *, include_token: bool) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "tool": self.tool,
            "title": self.title,
            "detail": self.detail,
            "arguments": self.arguments,
            "agent": self.agent,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }
        if include_token:
            data["token"] = self.token
        return data


def _preview_args(params: Any) -> Dict[str, Any]:
    """A bounded, JSON-safe copy of the arguments for display."""
    if not isinstance(params, dict):
        return {"value": str(params)[:_ARG_PREVIEW_CHARS]}
    out: Dict[str, Any] = {}
    for key, value in params.items():
        if str(key).startswith("_"):
            continue
        if isinstance(value, (int, float, bool)) or value is None:
            out[str(key)] = value
        else:
            text = str(value)
            if len(text) > _ARG_PREVIEW_CHARS:
                text = text[:_ARG_PREVIEW_CHARS] + "…"
            out[str(key)] = text
    return out


class ConfirmationBroker:
    """Process-wide registry of confirmations waiting for a human."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: Dict[str, PendingConfirmation] = {}
        self._bus: Optional[EventBus] = None
        self.enforce: bool = True
        self.timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


    def bind(
        self,
        bus: Optional[EventBus],
        *,
        enforce: bool = True,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """Attach to the server's event bus. Called once when routes mount."""
        self._bus = bus
        self.enforce = bool(enforce)
        self.timeout_seconds = float(timeout_seconds)

    def unbind(self) -> None:
        self._bus = None
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for item in pending:
            item.decision = False
            item.decided_by = "shutdown"
            item._event.set()

    @property
    def active(self) -> bool:
        return self._bus is not None


    def confirm(
        self,
        tool: str,
        arguments: Any = None,
        *,
        agent: str = "",
        title: str = "",
        detail: str = "",
        timeout: Optional[float] = None,
    ) -> bool:
        """Block until a person approves or denies. Returns ``True`` on approve."""
        bus = self._bus
        if bus is None:
            logger.warning("Confirmation for %s denied: no UI bound", tool)
            return False
        wait = self.timeout_seconds if timeout is None else float(timeout)
        now = time.time()
        item = PendingConfirmation(
            id=uuid.uuid4().hex[:16],
            tool=tool,
            title=title or f"Run '{tool}'?",
            detail=detail,
            arguments=_preview_args(arguments),
            agent=agent,
            created_at=now,
            expires_at=now + wait,
            token=secrets.token_urlsafe(24),
        )
        with self._lock:
            self._expire_locked()
            if len(self._pending) >= _MAX_PENDING:
                logger.warning("Confirmation for %s denied: queue full", tool)
                return False
            self._pending[item.id] = item
        bus.publish(EventType.CONFIRMATION_REQUESTED, item.public(include_token=True))
        approved = item._event.wait(wait) and bool(item.decision)
        with self._lock:
            self._pending.pop(item.id, None)
        if not item._event.is_set():
            item.decided_by = "timeout"
            bus.publish(
                EventType.CONFIRMATION_RESOLVED,
                {"id": item.id, "tool": tool, "approved": False, "by": "timeout"},
            )
        return approved

    def callback_for(self, agent: str = "") -> Callable[[str], bool]:
        """A ``confirm_callback`` for ToolExecutor that routes through the UI."""
        return UIConfirmCallback(self, agent)


    def list_pending(self, *, include_token: bool = True) -> List[Dict[str, Any]]:
        with self._lock:
            self._expire_locked()
            items = sorted(self._pending.values(), key=lambda p: p.created_at)
            return [p.public(include_token=include_token) for p in items]

    def resolve(self, confirmation_id: str, token: str, approved: bool) -> str:
        """Record a human decision. Returns ``ok``, ``not_found`` or ``bad_token``."""
        with self._lock:
            item = self._pending.get(confirmation_id)
            if item is None or item._event.is_set():
                return "not_found"
            if not secrets.compare_digest(
                str(token).encode("utf-8"), item.token.encode("utf-8")
            ):
                return "bad_token"
            item.decision = bool(approved)
            item.decided_by = "user"
            item._event.set()
        if self._bus is not None:
            self._bus.publish(
                EventType.CONFIRMATION_RESOLVED,
                {
                    "id": confirmation_id,
                    "tool": item.tool,
                    "approved": bool(approved),
                    "by": "user",
                },
            )
        return "ok"

    def _expire_locked(self) -> None:
        now = time.time()
        for key, item in list(self._pending.items()):
            if item.expires_at < now and not item._event.is_set():
                item.decision = False
                item.decided_by = "timeout"
                item._event.set()
                self._pending.pop(key, None)


class UIConfirmCallback:
    """Callable accepted anywhere a ``confirm_callback(prompt) -> bool`` is.

    ToolExecutor detects :meth:`confirm_tool` and passes structured data, so the
    UI shows the tool name and arguments instead of a pre-formatted sentence.
    """

    def __init__(self, broker: ConfirmationBroker, agent: str = "") -> None:
        self._broker = broker
        self._agent = agent

    def __call__(self, prompt: str) -> bool:
        return self._broker.confirm("tool", {}, agent=self._agent, title=prompt)

    def confirm_tool(self, tool: str, arguments: Any, agent: str = "") -> bool:
        return self._broker.confirm(tool, arguments, agent=agent or self._agent)


_BROKER = ConfirmationBroker()


def get_confirmation_broker() -> ConfirmationBroker:
    return _BROKER


def server_confirm_callback(agent: str = "") -> Callable[[str], bool]:
    """Confirmation policy for tool executors created by the HTTP server.

    ``security.enforce_tool_confirmation = true`` (default): ask a human via the
    UI. ``false``: legacy behaviour, approve automatically.
    """
    broker = get_confirmation_broker()
    if broker.active and broker.enforce:
        return broker.callback_for(agent)
    return _auto_approve


def _auto_approve(_prompt: str) -> bool:
    return True


__all__ = [
    "ConfirmationBroker",
    "PendingConfirmation",
    "UIConfirmCallback",
    "get_confirmation_broker",
    "server_confirm_callback",
]
