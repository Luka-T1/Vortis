"""HUD endpoints: human-only confirmations, gesture events, plugin listing."""

from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from vortis.core.events import EventType
from vortis.security.confirmation import get_confirmation_broker

router = APIRouter()

KNOWN_GESTURES = {
    "open_palm",
    "closed_fist",
    "pointing_up",
    "thumb_up",
    "thumb_down",
    "victory",
    "i_love_you",
    "swipe_left",
    "swipe_right",
    "swipe_up",
    "swipe_down",
    "pinch",
}


class ConfirmationDecision(BaseModel):
    token: str = Field(max_length=128)
    approve: bool


class GestureEvent(BaseModel):
    gesture: str = Field(max_length=32)
    hand: str = Field(default="", max_length=8)
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    device: str = Field(default="", max_length=60)
    action: str = Field(default="", max_length=40)


@router.get("/v1/confirmations")
async def list_confirmations() -> Dict[str, Any]:
    broker = get_confirmation_broker()
    items = broker.list_pending(include_token=True)
    return {"confirmations": items, "enforced": broker.enforce}


@router.post("/v1/confirmations/{confirmation_id}")
async def decide_confirmation(
    confirmation_id: str, body: ConfirmationDecision
) -> Dict[str, Any]:
    status = get_confirmation_broker().resolve(
        confirmation_id, body.token, body.approve
    )
    if status == "not_found":
        raise HTTPException(404, "No such pending confirmation (expired?)")
    if status == "bad_token":
        raise HTTPException(403, "Invalid confirmation token")
    return {"id": confirmation_id, "approved": body.approve}


@router.post("/v1/gestures")
async def report_gesture(body: GestureEvent, request: Request) -> Dict[str, Any]:
    gesture = body.gesture.strip().lower()
    if gesture not in KNOWN_GESTURES:
        raise HTTPException(400, f"Unknown gesture '{body.gesture}'")
    bus = _bus(request)
    payload = {
        "gesture": gesture,
        "hand": body.hand,
        "score": round(body.score, 3),
        "device": body.device,
        "action": body.action,
        "at": time.time(),
    }
    if bus is not None:
        bus.publish(EventType.GESTURE_DETECTED, payload)
    return payload


GESTURE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
    "gesture_recognizer/float16/1/gesture_recognizer.task"
)
GESTURE_MODEL_SHA256 = (
    "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482"
)
_model_lock = threading.Lock()


def _gesture_model_path() -> Path:
    from vortis.core.paths import get_config_dir

    return get_config_dir() / "models" / "gesture_recognizer.task"


def ensure_gesture_model() -> Path:
    path = _gesture_model_path()
    with _model_lock:
        if path.is_file() and _sha256(path) == GESTURE_MODEL_SHA256:
            return path
        import httpx

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        with httpx.stream(
            "GET", GESTURE_MODEL_URL, timeout=60, follow_redirects=True
        ) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
        if _sha256(tmp) != GESTURE_MODEL_SHA256:
            tmp.unlink(missing_ok=True)
            raise ValueError("gesture model checksum mismatch")
        tmp.replace(path)
        return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@router.get("/v1/hud/gesture-model")
async def gesture_model():
    import asyncio

    try:
        path = await asyncio.to_thread(ensure_gesture_model)
    except Exception as exc:
        raise HTTPException(
            503,
            "Gesture model unavailable. Put gesture_recognizer.task in "
            f"{_gesture_model_path().parent} or allow the server to download "
            f"it once ({exc}).",
        ) from exc
    return FileResponse(
        path,
        media_type="application/octet-stream",
        headers={"Cache-Control": "private, max-age=86400"},
    )


class DisplayBody(BaseModel):
    title: str = Field(default="", max_length=200)
    markdown: str = Field(default="", max_length=20000)
    chart: Optional[Dict[str, Any]] = None
    target: str = Field(default="all", max_length=20)
    source: str = Field(default="hud", max_length=40)


@router.post("/v1/display")
async def display_push(body: DisplayBody) -> Dict[str, Any]:
    from vortis.display import DisplayError, push

    try:
        return push(
            title=body.title,
            markdown=body.markdown,
            chart=body.chart,
            target=body.target,
            source=body.source,
        )
    except DisplayError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/v1/display/last")
async def display_last(target: str = "all") -> Dict[str, Any]:
    from vortis.display import last

    return {"item": last(target)}


@router.get("/v1/plugins")
async def list_plugins() -> Dict[str, Any]:
    from vortis.plugins import loaded_plugins, plugin_dirs

    return {
        "plugins": loaded_plugins(),
        "dirs": [str(p) for p in plugin_dirs()],
    }


def _bus(request: Request) -> Optional[Any]:
    from vortis.core.events import get_event_bus

    return getattr(request.app.state, "bus", None) or get_event_bus()


def bind_hud(app: Any) -> None:
    """Bind the confirmation broker to the app's bus (called at route setup)."""
    from vortis.core.events import get_event_bus

    config = getattr(app.state, "config", None)
    security = getattr(config, "security", None)
    enforce = bool(getattr(security, "enforce_tool_confirmation", True))
    bus = getattr(app.state, "bus", None) or get_event_bus()
    get_confirmation_broker().bind(bus, enforce=enforce)
    from vortis.display import bind_display

    bind_display(bus)
    try:
        from vortis.plugins import load_plugins

        load_plugins()
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Plugin discovery failed", exc_info=True)


__all__ = ["KNOWN_GESTURES", "bind_hud", "router"]
