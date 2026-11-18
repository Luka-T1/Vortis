"""HUD features: confirmation gate, outcomes, gestures, plugins, QR pairing."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from vortis.core.events import EventBus, EventType  # noqa: E402
from vortis.core.types import ToolCall, ToolResult  # noqa: E402
from vortis.security.confirmation import (  # noqa: E402
    get_confirmation_broker,
    server_confirm_callback,
)
from vortis.server.auth_middleware import AuthMiddleware  # noqa: E402
from vortis.server.hud_routes import router as hud_router  # noqa: E402
from vortis.server.pairing import (  # noqa: E402
    PairingStore,
    set_pairing_store,
)
from vortis.server.pairing import router as pairing_router  # noqa: E402
from vortis.tools._stubs import BaseTool, ToolExecutor, ToolSpec  # noqa: E402


class _Danger(BaseTool):
    tool_id = "danger"

    def __init__(self) -> None:
        self.ran = False

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="danger", description="x", parameters={}, requires_confirmation=True
        )

    def execute(self, **params):
        self.ran = True
        return ToolResult(tool_name="danger", content="deleted")


class _Unsure(BaseTool):
    tool_id = "unsure"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="unsure", description="x", parameters={})

    def execute(self, **params):
        return ToolResult(
            tool_name="unsure", content="launched", metadata={"outcome": "unverified"}
        )


def _app(bus: EventBus, api_key: str = "") -> FastAPI:
    app = FastAPI()
    app.state.bus = bus
    app.include_router(hud_router)
    app.include_router(pairing_router)
    if api_key:
        app.add_middleware(AuthMiddleware, api_key=api_key)
    return app


def _run_with_ui(bus: EventBus, approve: bool | None, token_override: str = ""):
    """Run the danger tool; a fake HUD answers through the HTTP endpoint."""
    get_confirmation_broker().bind(bus, timeout_seconds=3)
    client = TestClient(_app(bus))
    tool = _Danger()
    executor = ToolExecutor([tool], bus)
    seen = []

    def _on_request(event):
        seen.append(event.data)
        if approve is None:
            return

        def _press():
            r = client.post(
                f"/v1/confirmations/{event.data['id']}",
                json={
                    "token": token_override or event.data["token"],
                    "approve": approve,
                },
            )
            seen.append(r.status_code)

        threading.Thread(target=_press).start()

    bus.subscribe(EventType.CONFIRMATION_REQUESTED, _on_request)
    result = executor.execute(ToolCall(id="1", name="danger", arguments="{}"))
    return tool, result, seen


def test_confirm_button_approves():
    tool, result, seen = _run_with_ui(EventBus(), approve=True)
    assert tool.ran and result.success
    assert seen[0]["tool"] == "danger" and "token" in seen[0]
    assert result.metadata["outcome"] == "done"


def test_confirm_button_denies():
    tool, result, _ = _run_with_ui(EventBus(), approve=False)
    assert not tool.ran and not result.success
    assert "NOT done" in result.content
    assert result.metadata["outcome"] == "failed"


def test_forged_token_is_rejected_and_times_out():
    bus = EventBus()
    t0 = time.monotonic()
    tool, result, seen = _run_with_ui(bus, approve=True, token_override="guess")
    assert 403 in seen
    assert not tool.ran and not result.success
    assert time.monotonic() - t0 >= 2.5


def test_no_ui_bound_still_refuses():
    executor = ToolExecutor([_Danger()], EventBus())
    result = executor.execute(ToolCall(id="1", name="danger", arguments="{}"))
    assert not result.success and "no confirmation" in result.content


def test_server_callback_policy():
    broker = get_confirmation_broker()
    assert server_confirm_callback()("x") is True
    broker.bind(EventBus(), enforce=False)
    assert server_confirm_callback()("x") is True
    broker.bind(EventBus(), enforce=True)
    assert hasattr(server_confirm_callback("a"), "confirm_tool")


def test_unverified_outcome_is_flagged_to_model_and_ui():
    bus = EventBus(record_history=True)
    executor = ToolExecutor([_Unsure()], bus)
    result = executor.execute(ToolCall(id="1", name="unsure", arguments="{}"))
    assert result.success
    assert result.content.startswith("[status=unverified]")
    end = [e for e in bus.history if e.event_type == EventType.TOOL_CALL_END][-1]
    assert end.data["outcome"] == "unverified"


def test_gesture_event_published():
    bus = EventBus(record_history=True)
    client = TestClient(_app(bus))
    r = client.post("/v1/gestures", json={"gesture": "thumb_up", "score": 0.9})
    assert r.status_code == 200
    assert any(e.event_type == EventType.GESTURE_DETECTED for e in bus.history)
    assert client.post("/v1/gestures", json={"gesture": "rm -rf"}).status_code == 400


_PLUGIN = """
PLUGIN = {
    "name": "hello_plugin",
    "description": "Say hello",
    "parameters": {"type": "OBJECT", "properties": {"who": {"type": "STRING"}}},
    "confirm": True,
}

def run(parameters, player=None, session_memory=None):
    return "status=unverified action=hello who=" + parameters.get("who", "")
"""


def test_single_file_plugin(tmp_path: Path):
    from vortis.core.registry import ToolRegistry
    from vortis.plugins import load_plugins, loaded_plugins

    (tmp_path / "hello.py").write_text(_PLUGIN)
    (tmp_path / "broken.py").write_text("raise RuntimeError('boom')")
    (tmp_path / "_skip.py").write_text("raise SystemExit")
    assert load_plugins([tmp_path]) == ["hello_plugin"]
    tool = ToolRegistry.create("hello_plugin")
    assert tool.spec.parameters["properties"]["who"]["type"] == "string"
    assert tool.spec.requires_confirmation
    res = tool.execute(who="Milos")
    assert res.metadata["outcome"] == "unverified" and "Milos" in res.content
    errors = [p for p in loaded_plugins() if not p["loaded"]]
    assert len(errors) == 1 and "boom" in errors[0]["error"]


def test_qr_pairing_flow(tmp_path: Path):
    set_pairing_store(PairingStore(tmp_path / "devices.json"))
    key = "vt_sk_master"
    client = TestClient(_app(EventBus(), api_key=key))
    master = {"Authorization": f"Bearer {key}"}

    start = client.post("/v1/pairing/start", headers=master, json={"host": "10.0.0.5"})
    assert start.status_code == 200
    body = start.json()
    assert body["pair_url"].startswith("http://10.0.0.5:")
    assert "#code=" in body["pair_url"]

    claim = client.post("/pair/claim", json={"code": body["code"], "name": "Pixel"})
    assert claim.status_code == 200
    token = claim.json()["token"]
    assert client.post("/pair/claim", json={"code": body["code"]}).status_code == 400

    phone = {"Authorization": f"Bearer {token}"}
    assert client.get("/v1/pairing/devices", headers=phone).status_code == 200
    assert client.post("/v1/pairing/start", headers=phone).status_code == 403
    assert token not in (tmp_path / "devices.json").read_text()

    dev_id = claim.json()["device"]["id"]
    assert (
        client.delete(f"/v1/pairing/devices/{dev_id}", headers=master).status_code
        == 200
    )
    assert client.get("/v1/pairing/devices", headers=phone).status_code == 401


def test_pairing_codes_burn_after_guessing(tmp_path: Path):
    store = PairingStore(tmp_path / "d.json")
    code = store.new_code()["code"]
    for _ in range(10):
        assert store.claim("WRONG000", "x") is None
    assert store.claim(code, "x") is None


def test_display_push_and_tool():
    from vortis.tools.show_on_screen import ShowOnScreenTool

    bus = EventBus(record_history=True)
    client = TestClient(_app(bus))
    from vortis.display import bind_display

    bind_display(bus)
    chart = {
        "type": "bar",
        "x": ["Q1", "Q2"],
        "series": [{"name": "kg", "values": [1, 2.5]}],
    }
    r = client.post(
        "/v1/display", json={"title": "Masa", "chart": chart, "target": "tv"}
    )
    assert r.status_code == 200 and r.json()["chart"]["series"][0]["values"] == [
        1.0,
        2.5,
    ]
    assert (
        client.get("/v1/display/last", params={"target": "tv"}).json()["item"]["title"]
        == "Masa"
    )
    bad = {"type": "bar", "x": ["a"], "series": [{"name": "s", "values": ["x"]}]}
    assert client.post("/v1/display", json={"chart": bad}).status_code == 400
    assert client.post("/v1/display", json={"title": "empty"}).status_code == 400

    res = ShowOnScreenTool().execute(title="Notes", markdown="# hi", target="all")
    assert res.success and res.metadata["outcome"] == "unverified"
    pushes = [e for e in bus.history if e.event_type == EventType.DISPLAY_PUSH]
    assert len(pushes) == 2 and pushes[-1].data["markdown"] == "# hi"
