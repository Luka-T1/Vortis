"""``simulate``: open an interactive simulation with sliders on the user's screens."""

from __future__ import annotations

import json
import math
from typing import Any, Dict

from vortis.core.registry import ToolRegistry
from vortis.core.types import ToolResult
from vortis.tools._stubs import BaseTool, ToolSpec

_DESCRIPTION = (
    "Open an interactive simulation on the user's screen: sliders for the "
    "parameters and a live graph that recomputes as they move. Use it when the "
    "user says 'simulate', 'what happens if', 'show how X depends on Y', or wants "
    "to explore a model (physics, finance, growth, decay, queues, mechanics). "
    "The tool returns the computed key numbers so you can explain the result.\n"
    "Spec fields:\n"
    "- mode: 'function' (y = f(x)), 'ode' (state derivatives, RK4) or 'iterate' "
    "(discrete steps, x is the step number).\n"
    "- params: [{id, label, unit, min, max, value, step}] become sliders.\n"
    "- x: {id, label, unit, from, to, steps} the independent variable (time, "
    "month, distance). steps <= 2000.\n"
    "- state (ode/iterate): [{id, label, unit, initial, rate}] for ode, "
    "[{id, label, unit, initial, next}] for iterate. initial may use params.\n"
    "- series: [{id, label, unit, expr}] values computed from x, params, state "
    "and earlier series.\n"
    "- stop_when: optional expression, e.g. 'y < 0' to stop when a ball lands.\n"
    "- plot: {x: id of the horizontal axis (default x), y: [ids], x_label, y_label}.\n"
    "Expressions use + - * / ^ %, comparisons, && ||, numbers, ids, pi, e and "
    "sin cos tan asin acos atan atan2 sinh cosh tanh exp ln log log10 log2 sqrt "
    "abs pow hypot floor ceil round sign min max clamp if(cond, a, b). Angles "
    "are in radians. Example projectile: mode ode, params v0 and angle, state "
    "px rate 'vx', py rate 'vy', vx initial 'v0*cos(angle*pi/180)' rate 0, vy "
    "initial 'v0*sin(angle*pi/180)' rate '-9.81', stop_when 'py < 0', plot "
    "{x: 'px', y: ['py']}."
)


def _fmt(value: Any) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "n/a"
    return f"{value:.4g}"


@ToolRegistry.register("simulate")
class SimulateTool(BaseTool):
    tool_id = "simulate"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="simulate",
            description=_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {
                        "type": "string",
                        "description": (
                            "One or two sentences: what the model shows "
                            "and its assumptions."
                        ),
                    },
                    "simulation": {
                        "type": "object",
                        "description": (
                            "The spec: mode, params, x, state, series, stop_when, plot."
                        ),
                    },
                    "target": {
                        "type": "string",
                        "enum": ["all", "tv", "phone", "pc"],
                        "description": (
                            "Which screen; 'pc' unless the user names another."
                        ),
                    },
                },
                "required": ["title", "simulation"],
            },
            category="display",
            timeout_seconds=15,
        )

    def execute(self, **params: Any) -> ToolResult:
        from vortis.display import DisplayError, push
        from vortis.display.simulation import run_simulation, summarize

        raw = params.get("simulation")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                return self._fail("simulation must be a JSON object")
        if not isinstance(raw, dict):
            return self._fail("simulation must be an object")
        spec: Dict[str, Any] = {
            **raw,
            "title": params.get("title") or raw.get("title", ""),
            "description": params.get("description") or raw.get("description", ""),
        }
        try:
            item = push(
                title=str(spec["title"]),
                markdown=str(spec["description"] or ""),
                simulation=spec,
                target=str(params.get("target") or "pc"),
                source="assistant",
            )
        except DisplayError as exc:
            return self._fail(f"{exc}. Fix the spec and call simulate again.")

        sim = item["simulation"]
        rows = run_simulation(sim)
        x = sim["x"]
        lines = [
            f"Simulation '{sim['title'] or item['title']}' opened on "
            f"'{item['target']}' (id {item['id']}). Default parameters: "
            + ", ".join(
                f"{p['id']}={_fmt(p['value'])}{p['unit']}" for p in sim["params"]
            )
            + ".",
            f"Ran {len(rows)} steps of {x['id']} from {_fmt(x['from'])} "
            f"to {_fmt(rows[-1][x['id']])}.",
        ]
        for s in summarize(sim, rows):
            lines.append(
                f"{s['id']}: final {_fmt(s['final'])}, min {_fmt(s['min'])}, "
                f"max {_fmt(s['max'])} at {x['id']}={_fmt(s['x_at_max'])}"
            )
        lines.append(
            "The user can move the sliders; explain what the numbers mean and "
            "which parameter matters most. Whether a screen is open was not verified."
        )
        return ToolResult(
            tool_name="simulate",
            content="\n".join(lines),
            metadata={"outcome": "unverified", "display_id": item["id"]},
        )

    def _fail(self, message: str) -> ToolResult:
        return ToolResult(tool_name="simulate", content=message, success=False)
