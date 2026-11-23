"""Interactive simulations the HUD can re-run live as the user moves sliders.

A simulation is a small declarative spec: named parameters with ranges, an
independent variable, and arithmetic expressions. The same expression language
is evaluated here (to validate the spec and give the assistant real numbers to
talk about) and in the browser (to recompute instantly on every slider move).
No code from the model is ever executed; expressions are parsed by a closed
grammar of numbers, names, operators and a fixed set of math functions.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

MODES = ("function", "ode", "iterate")
MAX_PARAMS = 12
MAX_SERIES = 8
MAX_STEPS = 2000
MAX_EXPR = 400
_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")

Env = Dict[str, float]
Compiled = Callable[[Env], float]


class SimulationError(ValueError):
    pass


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _round(v: float, digits: float = 0) -> float:
    return round(v, int(digits))


def _sign(v: float) -> float:
    return (v > 0) - (v < 0)


def _if(c: float, a: float, b: float) -> float:
    return a if c else b


FUNCTIONS: Dict[str, Callable[..., float]] = {
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "exp": math.exp,
    "ln": math.log,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "sqrt": math.sqrt,
    "abs": abs,
    "pow": math.pow,
    "hypot": math.hypot,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": _round,
    "sign": _sign,
    "min": min,
    "max": max,
    "clamp": _clamp,
    "if": _if,
}
CONSTANTS = {"pi": math.pi, "e": math.e}

_TOKEN = re.compile(
    r"\s*(?:(?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"|(?P<op><=|>=|==|!=|&&|\|\||[-+*/^%(),<>!]))"
)

_BINARY = {
    "||": (1, lambda a, b: 1.0 if (a or b) else 0.0),
    "&&": (2, lambda a, b: 1.0 if (a and b) else 0.0),
    "==": (3, lambda a, b: 1.0 if a == b else 0.0),
    "!=": (3, lambda a, b: 1.0 if a != b else 0.0),
    "<": (4, lambda a, b: 1.0 if a < b else 0.0),
    ">": (4, lambda a, b: 1.0 if a > b else 0.0),
    "<=": (4, lambda a, b: 1.0 if a <= b else 0.0),
    ">=": (4, lambda a, b: 1.0 if a >= b else 0.0),
    "+": (5, lambda a, b: a + b),
    "-": (5, lambda a, b: a - b),
    "*": (6, lambda a, b: a * b),
    "/": (
        6,
        lambda a, b: a / b if b else math.copysign(math.inf, a) if a else math.nan,
    ),
    "%": (6, lambda a, b: math.fmod(a, b) if b else math.nan),
    "^": (8, lambda a, b: math.pow(a, b)),
}


def _tokenize(src: str) -> List[str]:
    tokens: List[str] = []
    pos = 0
    src = src.strip()
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m or m.end() == pos:
            raise SimulationError(f"unexpected character {src[pos]!r} in {src!r}")
        tokens.append(m.group(m.lastgroup or "op"))
        pos = m.end()
    return tokens


class _Parser:
    def __init__(self, src: str, names: Sequence[str]):
        self.src = src
        self.tokens = _tokenize(src)
        self.pos = 0
        self.names = set(names)
        self.used: set[str] = set()

    def peek(self) -> Optional[str]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> str:
        tok = self.peek()
        if tok is None:
            raise SimulationError(f"unexpected end of {self.src!r}")
        self.pos += 1
        return tok

    def expect(self, tok: str) -> None:
        if self.take() != tok:
            raise SimulationError(f"expected {tok!r} in {self.src!r}")

    def parse(self) -> Compiled:
        node = self.expr(0)
        if self.peek() is not None:
            raise SimulationError(f"unexpected {self.peek()!r} in {self.src!r}")
        return node

    def expr(self, min_prec: int) -> Compiled:
        left = self.unary()
        while True:
            op = self.peek()
            if op not in _BINARY:
                return left
            prec, fn = _BINARY[op]
            if prec < min_prec:
                return left
            self.take()
            right = self.expr(prec if op == "^" else prec + 1)
            left = (lambda f, a, b: lambda env: f(a(env), b(env)))(fn, left, right)

    def unary(self) -> Compiled:
        tok = self.peek()
        if tok == "-":
            self.take()
            inner = self.expr(7)
            return lambda env: -inner(env)
        if tok == "+":
            self.take()
            return self.expr(7)
        if tok == "!":
            self.take()
            inner = self.expr(7)
            return lambda env: 0.0 if inner(env) else 1.0
        return self.atom()

    def atom(self) -> Compiled:
        tok = self.take()
        if tok == "(":
            node = self.expr(0)
            self.expect(")")
            return node
        if tok[0].isdigit() or tok[0] == ".":
            value = float(tok)
            return lambda env: value
        if _ID.match(tok):
            if self.peek() == "(":
                fn = FUNCTIONS.get(tok)
                if fn is None:
                    raise SimulationError(f"unknown function {tok!r}")
                self.take()
                args: List[Compiled] = []
                if self.peek() != ")":
                    args.append(self.expr(0))
                    while self.peek() == ",":
                        self.take()
                        args.append(self.expr(0))
                self.expect(")")
                return lambda env: float(fn(*(a(env) for a in args)))
            if tok in self.names:
                self.used.add(tok)
                return lambda env: env[tok]
            if tok in CONSTANTS:
                value = CONSTANTS[tok]
                return lambda env: value
            raise SimulationError(f"unknown name {tok!r} in {self.src!r}")
        raise SimulationError(f"unexpected {tok!r} in {self.src!r}")


def compile_expr(src: Any, names: Sequence[str]) -> Compiled:
    """Compile an expression over *names*, the constants and FUNCTIONS only."""
    if isinstance(src, (int, float)) and not isinstance(src, bool):
        value = float(src)
        return lambda env: value
    if not isinstance(src, str) or not src.strip():
        raise SimulationError("expression must be a non-empty string")
    if len(src) > MAX_EXPR:
        raise SimulationError(f"expression longer than {MAX_EXPR} characters")
    compiled = _Parser(src, names).parse()

    def safe(env: Env) -> float:
        try:
            return compiled(env)
        except (ValueError, OverflowError, ZeroDivisionError, TypeError):
            return math.nan

    return safe


def _num(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise SimulationError(f"{field} must be a number") from exc
    if not math.isfinite(out):
        raise SimulationError(f"{field} must be finite")
    return out


def _ident(value: Any, field: str, taken: set[str]) -> str:
    ident = str(value or "")
    if not _ID.match(ident):
        raise SimulationError(f"{field} {ident!r} must be a short identifier like 'v0'")
    if ident in FUNCTIONS or ident in CONSTANTS:
        raise SimulationError(f"{field} {ident!r} clashes with a built-in name")
    if ident in taken:
        raise SimulationError(f"duplicate name {ident!r}")
    taken.add(ident)
    return ident


def _text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


@dataclass
class _Compiled:
    spec: Dict[str, Any]
    params: List[Dict[str, Any]]
    x_id: str
    x_from: float
    x_to: float
    steps: int
    initial: List[Compiled]
    update: List[Compiled]
    series: List[Compiled]
    stop: Optional[Compiled]


def validate_simulation(raw: Any) -> Dict[str, Any]:
    """Return a normalised simulation spec or raise SimulationError."""
    return _compile(raw).spec


def _compile(raw: Any) -> _Compiled:
    if not isinstance(raw, Mapping):
        raise SimulationError("simulation must be an object")
    mode = str(raw.get("mode", "function")).lower()
    if mode not in MODES:
        raise SimulationError(f"mode must be one of {', '.join(MODES)}")

    taken: set[str] = set()
    params_raw = raw.get("params") or []
    if not isinstance(params_raw, list) or len(params_raw) > MAX_PARAMS:
        raise SimulationError(f"params must be a list of at most {MAX_PARAMS}")
    params: List[Dict[str, Any]] = []
    for i, p in enumerate(params_raw):
        if not isinstance(p, Mapping):
            raise SimulationError("each param is {id, label, min, max, value}")
        pid = _ident(p.get("id"), "param id", taken)
        lo = _num(p.get("min", 0), f"params[{i}].min")
        hi = _num(p.get("max", 1), f"params[{i}].max")
        if hi <= lo:
            raise SimulationError(f"param {pid!r}: max must be greater than min")
        value = _clamp(_num(p.get("value", lo), f"params[{i}].value"), lo, hi)
        step = p.get("step")
        step_v = (
            _num(step, f"params[{i}].step") if step is not None else (hi - lo) / 100
        )
        if step_v <= 0:
            raise SimulationError(f"param {pid!r}: step must be positive")
        params.append(
            {
                "id": pid,
                "label": _text(p.get("label") or pid, 60),
                "unit": _text(p.get("unit"), 16),
                "min": lo,
                "max": hi,
                "step": step_v,
                "value": value,
            }
        )

    x_raw = raw.get("x") or {}
    if not isinstance(x_raw, Mapping):
        raise SimulationError("x must be an object {id, from, to, steps}")
    x_id = _ident(x_raw.get("id") or ("n" if mode == "iterate" else "t"), "x id", taken)
    x_from = _num(x_raw.get("from", 0), "x.from")
    x_to = _num(x_raw.get("to", 10), "x.to")
    if x_to <= x_from:
        raise SimulationError("x.to must be greater than x.from")
    default_steps = int(x_to - x_from) if mode == "iterate" else 400
    steps = int(_num(x_raw.get("steps", default_steps), "x.steps"))
    if not 1 <= steps <= MAX_STEPS:
        raise SimulationError(f"x.steps must be between 1 and {MAX_STEPS}")

    param_ids = [p["id"] for p in params]
    state_out: List[Dict[str, Any]] = []
    initial: List[Compiled] = []
    update: List[Compiled] = []
    if mode in ("ode", "iterate"):
        state_raw = raw.get("state") or []
        if not isinstance(state_raw, list) or not 1 <= len(state_raw) <= MAX_SERIES:
            raise SimulationError(f"{mode} needs 1 to {MAX_SERIES} state variables")
        state_ids = [
            _ident(s.get("id") if isinstance(s, Mapping) else None, "state id", taken)
            for s in state_raw
        ]
        key = "rate" if mode == "ode" else "next"
        scope = [*param_ids, x_id, *state_ids]
        for sid, s in zip(state_ids, state_raw):
            init_src = s.get("initial", 0)
            step_src = s.get(key)
            if step_src is None:
                raise SimulationError(f"state {sid!r} needs '{key}'")
            initial.append(compile_expr(init_src, param_ids))
            update.append(compile_expr(step_src, scope))
            state_out.append(
                {
                    "id": sid,
                    "label": _text(s.get("label") or sid, 60),
                    "unit": _text(s.get("unit"), 16),
                    "initial": init_src,
                    key: step_src,
                }
            )

    series_raw = raw.get("series") or []
    if not isinstance(series_raw, list) or len(series_raw) > MAX_SERIES:
        raise SimulationError(f"series must be a list of at most {MAX_SERIES}")
    if mode == "function" and not series_raw:
        raise SimulationError("function mode needs at least one series {id, expr}")
    scope = [*param_ids, x_id, *(s["id"] for s in state_out)]
    series_out: List[Dict[str, Any]] = []
    series_fns: List[Compiled] = []
    for s in series_raw:
        if not isinstance(s, Mapping):
            raise SimulationError("each series is {id, label, expr}")
        sid = _ident(s.get("id"), "series id", taken)
        series_fns.append(compile_expr(s.get("expr"), scope))
        series_out.append(
            {
                "id": sid,
                "label": _text(s.get("label") or sid, 60),
                "unit": _text(s.get("unit"), 16),
                "expr": s.get("expr"),
            }
        )
        scope.append(sid)

    stop_src = raw.get("stop_when")
    stop = compile_expr(stop_src, scope) if stop_src not in (None, "") else None

    plottable = [s["id"] for s in state_out] + [s["id"] for s in series_out]
    plot_raw = raw.get("plot") or {}
    if not isinstance(plot_raw, Mapping):
        raise SimulationError("plot must be an object {x, y}")
    plot_x = str(plot_raw.get("x") or x_id)
    if plot_x != x_id and plot_x not in plottable:
        raise SimulationError(f"plot.x {plot_x!r} is not a variable of this simulation")
    plot_y = plot_raw.get("y") or [p for p in plottable if p != plot_x]
    if isinstance(plot_y, str):
        plot_y = [plot_y]
    plot_y = [str(y) for y in plot_y][:MAX_SERIES]
    for y in plot_y:
        if y not in plottable:
            raise SimulationError(f"plot.y {y!r} is not a state or series id")
    if not plot_y:
        raise SimulationError("nothing to plot")

    spec = {
        "mode": mode,
        "title": _text(raw.get("title"), 120),
        "description": _text(raw.get("description"), 600),
        "params": params,
        "x": {
            "id": x_id,
            "label": _text(x_raw.get("label") or x_id, 60),
            "unit": _text(x_raw.get("unit"), 16),
            "from": x_from,
            "to": x_to,
            "steps": steps,
        },
        "state": state_out,
        "series": series_out,
        "stop_when": stop_src or "",
        "plot": {
            "x": plot_x,
            "y": plot_y,
            "x_label": _text(plot_raw.get("x_label"), 60),
            "y_label": _text(plot_raw.get("y_label"), 60),
            "type": "area" if plot_raw.get("type") == "area" else "line",
        },
    }
    return _Compiled(
        spec, params, x_id, x_from, x_to, steps, initial, update, series_fns, stop
    )


def run_simulation(
    spec: Any, values: Optional[Mapping[str, float]] = None
) -> List[Dict[str, float]]:
    """Evaluate a simulation: one row per step with x, state and series values."""
    c = _compile(spec)
    env: Env = {
        p["id"]: float((values or {}).get(p["id"], p["value"])) for p in c.params
    }
    state_ids = [s["id"] for s in c.spec["state"]]
    series_ids = [s["id"] for s in c.spec["series"]]
    mode = c.spec["mode"]
    h = (c.x_to - c.x_from) / c.steps
    state = [f(env) for f in c.initial]
    rows: List[Dict[str, float]] = []

    def derive(x: float, st: Sequence[float]) -> Dict[str, float]:
        local = dict(env)
        local[c.x_id] = x
        local.update(zip(state_ids, st))
        for sid, fn in zip(series_ids, c.series):
            local[sid] = fn(local)
        return local

    def rates(x: float, st: Sequence[float]) -> List[float]:
        local = dict(env)
        local[c.x_id] = x
        local.update(zip(state_ids, st))
        return [f(local) for f in c.update]

    for i in range(c.steps + 1):
        x = c.x_from + i * h
        local = derive(x, state)
        rows.append({k: local[k] for k in (c.x_id, *state_ids, *series_ids)})
        if c.stop is not None and i > 0 and c.stop(local):
            break
        if i == c.steps:
            break
        if mode == "ode":
            k1 = rates(x, state)
            k2 = rates(x + h / 2, [s + h / 2 * k for s, k in zip(state, k1)])
            k3 = rates(x + h / 2, [s + h / 2 * k for s, k in zip(state, k2)])
            k4 = rates(x + h, [s + h * k for s, k in zip(state, k3)])
            state = [
                s + h / 6 * (a + 2 * b + 2 * cc + d)
                for s, a, b, cc, d in zip(state, k1, k2, k3, k4)
            ]
        elif mode == "iterate":
            state = rates(x, state)
    return rows


def summarize(
    spec: Mapping[str, Any], rows: Sequence[Mapping[str, float]]
) -> List[Dict[str, Any]]:
    """Final, min and max (with the x where the max occurs) of each plotted variable."""
    x_id = spec["x"]["id"]
    out: List[Dict[str, Any]] = []
    for y in spec["plot"]["y"]:
        points = [(r[x_id], r[y]) for r in rows if math.isfinite(r.get(y, math.nan))]
        if not points:
            out.append(
                {"id": y, "final": None, "min": None, "max": None, "x_at_max": None}
            )
            continue
        best = max(points, key=lambda p: p[1])
        out.append(
            {
                "id": y,
                "final": points[-1][1],
                "min": min(p[1] for p in points),
                "max": best[1],
                "x_at_max": best[0],
            }
        )
    return out


__all__ = [
    "FUNCTIONS",
    "SimulationError",
    "compile_expr",
    "run_simulation",
    "summarize",
    "validate_simulation",
]
