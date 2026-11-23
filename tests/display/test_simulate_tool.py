"""Tests for the ``simulate`` tool and simulation display items."""

from __future__ import annotations

import json

import pytest

from vortis.core.events import EventBus, EventType
from vortis.display import DisplayError, bind_display, last, push
from vortis.tools.simulate import SimulateTool

PROJECTILE = {
    "mode": "ode",
    "params": [
        {
            "id": "v0",
            "label": "Brzina",
            "unit": "m/s",
            "min": 1,
            "max": 100,
            "value": 20,
        },
        {"id": "angle", "label": "Ugao", "unit": "°", "min": 1, "max": 89, "value": 45},
    ],
    "x": {"id": "t", "label": "Vreme", "unit": "s", "from": 0, "to": 10, "steps": 1000},
    "state": [
        {"id": "px", "initial": "0", "rate": "vx"},
        {"id": "py", "initial": "0", "rate": "vy"},
        {"id": "vx", "initial": "v0*cos(angle*pi/180)", "rate": "0"},
        {"id": "vy", "initial": "v0*sin(angle*pi/180)", "rate": "-9.81"},
    ],
    "stop_when": "py < 0",
    "plot": {"x": "px", "y": ["py"]},
}


@pytest.fixture
def bus():
    instance = EventBus(record_history=True)
    bind_display(instance)
    return instance


def test_tool_opens_simulation_and_reports_numbers(bus):
    result = SimulateTool().execute(
        title="Kosi hitac", simulation=PROJECTILE, description="Bez otpora vazduha."
    )

    assert result.success
    assert result.metadata["outcome"] == "unverified"
    assert "v0=20m/s" in result.content
    peak = 20**2 * 0.5 / (2 * 9.81)
    line = next(row for row in result.content.splitlines() if row.startswith("py:"))
    assert f"max {peak:.4g}" in line
    pushed = [e.data for e in bus.history if e.event_type == EventType.DISPLAY_PUSH]
    assert pushed[-1]["simulation"]["mode"] == "ode"
    assert pushed[-1]["target"] == "pc"
    assert pushed[-1]["markdown"] == "Bez otpora vazduha."


def test_tool_accepts_json_string(bus):
    result = SimulateTool().execute(
        title="Hitac", simulation=json.dumps(PROJECTILE), target="tv"
    )
    assert result.success
    assert last("tv")["simulation"]["x"]["id"] == "t"


def test_tool_reports_invalid_spec(bus):
    broken = {**PROJECTILE, "stop_when": "__import__('os')"}
    result = SimulateTool().execute(title="Loše", simulation=broken)
    assert not result.success
    assert "call simulate again" in result.content
    assert not SimulateTool().execute(title="x", simulation="not json").success


def test_push_clamps_values_and_keeps_id(bus):
    item = push(
        title="Hitac",
        simulation=PROJECTILE,
        values={"v0": 500, "angle": "30", "unknown": 1},
        item_id="sim-1",
    )
    assert item["id"] == "sim-1"
    assert item["values"] == {"v0": 100.0, "angle": 30.0}


def test_push_rejects_bad_simulation(bus):
    with pytest.raises(DisplayError, match="simulation"):
        push(title="x", simulation={"mode": "magic"})
