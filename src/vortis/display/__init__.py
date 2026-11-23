"""Push text and charts to a screen (TV, phone, PC) instantly.

Any client showing ``/display`` (e.g. the TV's browser) or the HUD receives a
``display_push`` event over the existing WebSocket and renders it at once.
The agent uses the ``show_on_screen`` tool; the HUD's "send to TV" gesture or
voice command uses ``POST /v1/display``.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from vortis.core.events import EventBus, EventType, get_event_bus

KINDS = ("markdown", "chart", "simulation")
CHART_TYPES = ("line", "bar", "area", "scatter", "pie")
MAX_POINTS = 5000
MAX_TEXT = 20000

_lock = threading.Lock()
_last: Dict[str, Dict[str, Any]] = {}
_bus: Optional[EventBus] = None


def bind_display(bus: Optional[EventBus]) -> None:
    global _bus
    _bus = bus


class DisplayError(ValueError):
    pass


def validate_chart(chart: Any) -> Dict[str, Any]:
    """Accept a small, safe chart spec: {type, x: [...], series: [{name, values}]}."""
    if not isinstance(chart, dict):
        raise DisplayError("chart must be an object")
    ctype = str(chart.get("type", "line")).lower()
    if ctype not in CHART_TYPES:
        raise DisplayError(f"chart.type must be one of {', '.join(CHART_TYPES)}")
    x = chart.get("x") or []
    series = chart.get("series") or []
    if not isinstance(x, list) or not isinstance(series, list) or not series:
        raise DisplayError("chart needs x (list) and series (non-empty list)")
    if len(x) > MAX_POINTS:
        raise DisplayError(f"at most {MAX_POINTS} points")
    clean: List[Dict[str, Any]] = []
    for item in series[:12]:
        if not isinstance(item, dict):
            raise DisplayError("each series is {name, values}")
        values = item.get("values") or []
        if not isinstance(values, list) or (x and len(values) != len(x)):
            raise DisplayError("series values must match x in length")
        nums = []
        for v in values:
            try:
                nums.append(None if v is None else float(v))
            except (TypeError, ValueError) as exc:
                raise DisplayError("series values must be numbers") from exc
        clean.append({"name": str(item.get("name", ""))[:60], "values": nums})
    return {
        "type": ctype,
        "x": [str(v)[:40] if not isinstance(v, (int, float)) else v for v in x],
        "series": clean,
        "x_label": str(chart.get("x_label", ""))[:60],
        "y_label": str(chart.get("y_label", ""))[:60],
    }


def push(
    *,
    title: str = "",
    markdown: str = "",
    chart: Any = None,
    simulation: Any = None,
    values: Optional[Dict[str, float]] = None,
    target: str = "all",
    source: str = "",
    item_id: str = "",
) -> Dict[str, Any]:
    """Publish one item to the screens. ``target``: 'tv', 'phone', 'pc' or 'all'.

    Re-using ``item_id`` updates a panel that is already open (for example a
    simulation whose sliders moved on another device).
    """
    if not markdown and chart is None and simulation is None:
        raise DisplayError("nothing to show: give markdown, chart or simulation")
    sim = None
    if simulation is not None:
        from vortis.display.simulation import SimulationError, validate_simulation

        try:
            sim = validate_simulation(simulation)
        except SimulationError as exc:
            raise DisplayError(f"simulation: {exc}") from exc
    clean_values: Dict[str, float] = {}
    if sim is not None and values:
        bounds = {p["id"]: (p["min"], p["max"]) for p in sim["params"]}
        for key, val in values.items():
            if key in bounds:
                try:
                    lo, hi = bounds[key]
                    clean_values[key] = min(hi, max(lo, float(val)))
                except (TypeError, ValueError):
                    continue
    item = {
        "id": (item_id or uuid.uuid4().hex)[:32],
        "title": str(title)[:200],
        "markdown": str(markdown)[:MAX_TEXT],
        "chart": validate_chart(chart) if chart is not None else None,
        "simulation": sim,
        "values": clean_values,
        "target": (target or "all").lower()[:20],
        "source": source[:40],
        "at": time.time(),
    }
    with _lock:
        _last[item["target"]] = item
        _last["all"] = item
    bus = _bus or get_event_bus()
    bus.publish(EventType.DISPLAY_PUSH, item)
    return item


def last(target: str = "all") -> Optional[Dict[str, Any]]:
    with _lock:
        return _last.get(target) or _last.get("all")


def _reset_for_tests() -> None:
    global _bus
    with _lock:
        _last.clear()
    _bus = None


__all__ = ["DisplayError", "bind_display", "last", "push", "validate_chart"]
