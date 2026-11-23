import math

import pytest

from vortis.display.simulation import (
    SimulationError,
    compile_expr,
    run_simulation,
    summarize,
    validate_simulation,
)


def ev(src, **env):
    return compile_expr(src, list(env))(env)


def test_expression_precedence_and_functions():
    assert ev("1 + 2 * 3 ^ 2") == 19
    assert ev("-2 ^ 2") == -4
    assert ev("2 ^ 3 ^ 2") == 512
    assert ev("max(a, b) + sqrt(16)", a=1, b=3) == 7
    assert ev("if(a > 1, 10, 20)", a=2) == 10
    assert ev("sin(pi / 2)") == pytest.approx(1)
    assert ev("1e-3 * 1000") == pytest.approx(1)


def test_expression_rejects_unknown_names_and_code():
    for bad in ("__import__('os')", "a.b", "x[0]", "open(1)", "lambda: 1", "y + 1"):
        with pytest.raises(SimulationError):
            compile_expr(bad, ["x"])


def test_math_errors_become_nan():
    assert math.isnan(ev("sqrt(-1)"))
    assert math.isnan(ev("0 / 0"))


PROJECTILE = {
    "mode": "ode",
    "title": "Kosi hitac",
    "params": [
        {
            "id": "v0",
            "label": "Početna brzina",
            "min": 1,
            "max": 50,
            "value": 20,
            "unit": "m/s",
        },
        {"id": "angle", "label": "Ugao", "min": 1, "max": 89, "value": 45, "unit": "°"},
        {"id": "g", "min": 1, "max": 20, "value": 9.81},
    ],
    "x": {"id": "t", "from": 0, "to": 10, "steps": 2000},
    "state": [
        {"id": "px", "initial": 0, "rate": "vx"},
        {"id": "py", "initial": 0, "rate": "vy"},
        {"id": "vx", "initial": "v0 * cos(angle * pi / 180)", "rate": 0},
        {"id": "vy", "initial": "v0 * sin(angle * pi / 180)", "rate": "-g"},
    ],
    "stop_when": "py < 0",
    "plot": {"x": "px", "y": ["py"]},
}


def test_ode_projectile_matches_closed_form():
    rows = run_simulation(PROJECTILE)
    summary = summarize(validate_simulation(PROJECTILE), rows)[0]
    assert summary["max"] == pytest.approx(20**2 / (4 * 9.81), rel=1e-3)
    assert rows[-1]["px"] == pytest.approx(20**2 / 9.81, rel=1e-2)


def test_slider_values_override_defaults():
    rows = run_simulation(PROJECTILE, {"v0": 10})
    assert max(r["py"] for r in rows) == pytest.approx(10**2 / (4 * 9.81), rel=1e-3)


def test_iterate_loan_balance():
    spec = {
        "mode": "iterate",
        "params": [
            {"id": "P", "min": 1000, "max": 50000, "value": 10000},
            {"id": "r", "min": 0, "max": 20, "value": 6},
            {"id": "years", "min": 1, "max": 30, "value": 5},
        ],
        "x": {"id": "m", "from": 0, "to": 60},
        "state": [
            {"id": "balance", "initial": "P", "next": "balance * (1 + r/1200) - pay"}
        ],
        "series": [
            {"id": "pay", "expr": "P * (r/1200) / (1 - (1 + r/1200) ^ (-years*12))"}
        ],
        "plot": {"y": ["balance"]},
    }
    with pytest.raises(SimulationError):
        validate_simulation(spec)
    spec["state"][0]["next"] = (
        "balance * (1 + r/1200) - P * (r/1200) / (1 - (1 + r/1200) ^ (-years*12))"
    )
    rows = run_simulation(spec)
    assert len(rows) == 61
    assert rows[-1]["balance"] == pytest.approx(0, abs=1e-6)


def test_function_mode_and_plot_defaults():
    spec = validate_simulation(
        {
            "params": [{"id": "k", "min": 0, "max": 2, "value": 1}],
            "x": {"id": "x", "from": 0, "to": 1, "steps": 10},
            "series": [{"id": "y", "expr": "k * x ^ 2"}, {"id": "z", "expr": "y + 1"}],
        }
    )
    assert spec["plot"]["y"] == ["y", "z"]
    rows = run_simulation(spec)
    assert rows[-1]["z"] == pytest.approx(2)


@pytest.mark.parametrize(
    "patch, message",
    [
        ({"mode": "quantum"}, "mode"),
        ({"params": [{"id": "sin", "min": 0, "max": 1}]}, "built-in"),
        ({"params": [{"id": "a", "min": 2, "max": 1}]}, "max"),
        ({"x": {"from": 0, "to": 1, "steps": 99999}}, "steps"),
        ({"plot": {"y": ["nope"]}}, "plot.y"),
    ],
)
def test_validation_errors(patch, message):
    spec = {"series": [{"id": "y", "expr": "t"}], **patch}
    with pytest.raises(SimulationError, match=message):
        validate_simulation(spec)
