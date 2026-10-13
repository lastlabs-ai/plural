from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from plural import App, Environment, Runtime
from plural.apps.openapi import OpenAPIApp
from plural.apps.replay import ReplayApp
from plural.environments.definition import EnvironmentDefinition

TOKEN = "openapi-token-7f3a91"


class _Orders(BaseHTTPRequestHandler):
    orders: dict[str, dict[str, Any]] = {}
    seen_auth: list[str] = []

    def log_message(self, *args: Any) -> None:
        del args

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        type(self).seen_auth.append(self.headers.get("Authorization", ""))
        if self.path.startswith("/orders/"):
            order = self.orders.get(self.path.rsplit("/", 1)[1])
            if order is None:
                self._send(404, {"detail": "no such order"})
            else:
                self._send(200, order)
            return
        status = self.path.partition("status=")[2]
        self._send(
            200,
            [item for item in self.orders.values() if not status or item["status"] == status],
        )

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        order = {"id": str(len(self.orders) + 1), "status": "open", **body}
        self.orders[order["id"]] = order
        self._send(201, order)


@pytest.fixture
def api() -> Iterator[str]:
    _Orders.orders = {"1": {"id": "1", "item": "lamp", "status": "shipped"}}
    _Orders.seen_auth = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Orders)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Orders", "version": "1"},
    "paths": {
        "/orders": {
            "get": {
                "operationId": "listOrders",
                "summary": "List orders.",
                "parameters": [{"name": "status", "in": "query", "schema": {"type": "string"}}],
            },
            "post": {
                "operationId": "createOrder",
                "summary": "Place an order.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/New"}}
                    },
                },
            },
        },
        "/orders/{id}": {
            "parameters": [
                {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
            ],
            "get": {"operationId": "getOrder", "summary": "Get one order."},
        },
    },
    "components": {
        "schemas": {
            "New": {
                "type": "object",
                "properties": {"item": {"type": "string"}, "quantity": {"type": "integer"}},
                "required": ["item"],
            }
        }
    },
}


def _orders_env(tmp_path: Path, url: str) -> Environment:
    (tmp_path / "orders.json").write_text(json.dumps({**SPEC, "servers": [{"url": url}]}))
    app = App.openapi(
        "orders",
        spec="orders.json",
        headers={"Authorization": "Bearer ${ORDERS_TOKEN}"},
        secrets=["ORDERS_TOKEN"],
    )
    return Environment(apps=[app], runtime=Runtime.local(), source=tmp_path)


def test_openapi_operations_become_actions_with_their_routes(
    tmp_path: Path, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORDERS_TOKEN", TOKEN)
    environment = _orders_env(tmp_path, api)
    definition = environment.definition()
    actions = {item.name: item for item in definition.apps[0].actions}
    assert set(actions) == {"listOrders", "createOrder", "getOrder"}
    assert actions["listOrders"].mutates_state is False
    assert actions["createOrder"].mutates_state is True
    assert actions["createOrder"].parameters["required"] == ["item"]
    assert actions["getOrder"].binding == {
        "method": "GET",
        "path": "/orders/{id}",
        "path_params": ["id"],
        "query_params": [],
        "header_params": [],
        "body_fields": None,
    }
    assert definition.apps[0].control == "live"
    assert [item.name for item in definition.secrets] == ["ORDERS_TOKEN"]

    environment.reset()
    observation, *_ = environment.step("getOrder", id="1")
    assert observation == {"id": "1", "item": "lamp", "status": "shipped"}
    observation, *_ = environment.step("createOrder", item="desk", quantity=2)
    assert observation["item"] == "desk" and observation["quantity"] == 2
    observation, *_ = environment.step("listOrders", status="open")
    assert [item["item"] for item in observation["items"]] == ["desk"]
    _obs, _reward, _done, _cut, info = environment.step("getOrder", id="99")
    assert info["error"].startswith("HTTP 404")
    assert set(_Orders.seen_auth) == {f"Bearer {TOKEN}"}
    environment.close()


def test_openapi_definition_rebuilds_from_pinned_actions(
    tmp_path: Path, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORDERS_TOKEN", TOKEN)
    definition = _orders_env(tmp_path, api).definition()
    restored = EnvironmentDefinition.model_validate_json(definition.model_dump_json())
    rebuilt = Environment._from_definition(restored, root=tmp_path)
    rebuilt.reset()
    observation, *_ = rebuilt.step("getOrder", id="1")
    assert observation["item"] == "lamp"
    rebuilt.close()


def test_openapi_headers_must_declare_their_secrets(tmp_path: Path) -> None:
    (tmp_path / "orders.json").write_text(json.dumps(SPEC))
    with pytest.raises(ValueError, match="list them in credentials"):
        OpenAPIApp(name="orders", spec="orders.json", headers={"X-Key": "${HIDDEN_KEY}"})


RECORDED = [
    {"role": "user", "content": "Find order 1."},
    {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "c1",
                "function": {"name": "get_order", "arguments": json.dumps({"id": "1"})},
            }
        ],
    },
    {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"id": "1", "item": "lamp"})},
    {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "c2",
                "function": {
                    "name": "refund",
                    "arguments": json.dumps({"id": "1", "reason": "broken"}),
                },
            }
        ],
    },
    {"role": "tool", "tool_call_id": "c2", "content": "Refunded."},
]


def test_replay_answers_recorded_calls_and_flags_misses(tmp_path: Path) -> None:
    (tmp_path / "trace.json").write_text(json.dumps({"messages": RECORDED}))
    app = App.replay("orders", recordings="trace.json", read_only=["get_order"])
    environment = Environment(apps=[app], runtime=Runtime.local(), source=tmp_path)
    definition = environment.definition()
    assert definition.apps[0].control == "replayed"
    actions = {item.name: item for item in definition.actions}
    assert actions["get_order"].mutates_state is False
    assert set(actions["refund"].parameters["properties"]) == {"id", "reason"}

    environment.reset()
    observation, _r, _t, _u, info = environment.step("get_order", id="1")
    assert observation == {"id": "1", "item": "lamp"}
    assert info.get("off_recording") is None
    observation, _r, _t, _u, info = environment.step("refund", id="1", reason="late")
    assert observation == {"text": "Refunded."}
    assert info["off_recording"] is True
    assert environment.apps[0].snapshot() == {"calls": 2, "off_recording": 1}
    environment.close()

    strict = ReplayApp(name="orders", recordings="trace.json", fallback="error")
    strict.workspace = tmp_path
    with pytest.raises(ValueError, match="No recorded refund call"):
        strict.call("refund", {"id": "2"})


def test_environment_yaml_lists_apps_of_every_connected_kind(
    tmp_path: Path, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import textwrap

    from project_fixtures import write_project

    from plural.project import ResourceRef, Workspace

    project = write_project(tmp_path / "desk")
    folder = project.root / "environments/backoffice"
    folder.mkdir(parents=True)
    (folder / "orders.json").write_text(json.dumps({**SPEC, "servers": [{"url": api}]}))
    (folder / "trace.json").write_text(json.dumps({"messages": RECORDED}))
    (folder / "README.md").write_text("# Back office\n\n## Overview\n\nOrders and refunds.\n")
    (folder / "environment.yaml").write_text(
        textwrap.dedent(
            """
            name: backoffice
            version: 0.1.0
            description: Orders, customers, and recorded refunds.
            readme: README.md
            runtime:
              provider: local
            apps:
              - name: orders
                openapi:
                  spec: orders.json
                  operations: [getOrder, listOrders]
              - name: crm
                mcp:
                  server: plural.mcp.files:server
                  secrets: [CRM_EXPORT_TOKEN]
                  remote: false
              - name: payments
                replay:
                  recordings: trace.json
            """
        ).lstrip()
    )
    loaded = Workspace(project).load(ResourceRef("environment", "backoffice"))
    definition = loaded.value.definition()
    assert {app.name: app.control for app in definition.apps} == {
        "orders": "live",
        "crm": "owned",
        "payments": "replayed",
    }
    assert "getOrder" in {item.name for item in definition.actions}
    assert {"list_files", "query", "refund"} <= {item.name for item in definition.actions}

    from typer.testing import CliRunner

    from plural.cli.main import app

    monkeypatch.chdir(project.root)
    monkeypatch.delenv("CRM_EXPORT_TOKEN", raising=False)
    result = CliRunner().invoke(app, ["env", "validate", "backoffice", "--json"])
    assert result.exit_code == 0, result.output
    summary = {item["name"]: item for item in json.loads(result.output)["apps"]}
    assert summary["crm"]["secrets"] == [
        {"name": "CRM_EXPORT_TOKEN", "required": True, "set": False, "source": None}
    ]
    assert {"name": "getOrder", "mutates_state": False} in summary["orders"]["actions"]


def test_openapi_path_parameters_cannot_leave_their_segment(
    tmp_path: Path, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORDERS_TOKEN", TOKEN)
    environment = _orders_env(tmp_path, api)
    environment.reset()
    for value in ("..", ".", "1\r\nX-Injected: yes"):
        *_, info = environment.step("getOrder", id=value)
        assert "must name one item" in info["error"]
    *_, info = environment.step("getOrder", id="../orders")
    assert info["error"].startswith("HTTP 404")
    environment.close()


def test_openapi_request_errors_never_show_a_credential(
    tmp_path: Path, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORDERS_TOKEN", f"{TOKEN}\r")
    environment = _orders_env(tmp_path, api)
    environment.reset()
    *_, info = environment.step("getOrder", id="1")
    assert "could not build a valid request" in info["error"]
    assert TOKEN not in info["error"]
    environment.close()


def test_a_fetched_openapi_document_does_not_choose_where_credentials_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import plural.apps.openapi as openapi

    document = {**SPEC, "servers": [{"url": "https://elsewhere.example"}]}
    monkeypatch.setattr(openapi, "load_document", lambda *args, **kwargs: document)
    monkeypatch.setenv("ORDERS_TOKEN", TOKEN)
    app = OpenAPIApp(
        name="orders",
        spec="https://vendor.example/openapi.json",
        headers={"Authorization": "Bearer ${ORDERS_TOKEN}"},
        secrets=["ORDERS_TOKEN"],
    )
    with pytest.raises(ValueError, match="needs base_url"):
        app.call("getOrder", {"id": "1"})


def test_an_mcp_server_holding_a_secret_is_remote_unless_declared_local() -> None:
    from plural.apps.definition import settings_control

    server = {"server": "plural.mcp.files:server", "secrets": ["DB_TOKEN"]}
    assert settings_control({"kind": "mcp", "config": server}) == "live"
    assert settings_control({"kind": "mcp", "config": {**server, "remote": False}}) == "owned"
    assert settings_control({"kind": "mcp", "config": {"command": ["srv"]}}) == "owned"


def test_a_one_line_jsonl_recording_loads(tmp_path: Path) -> None:
    from plural.apps.replay import read_recordings

    recording = {"action": "get_order", "arguments": {"id": "1"}, "result": {"id": "1"}}
    path = tmp_path / "calls.jsonl"
    path.write_text(json.dumps(recording) + "\n")
    assert read_recordings(path) == [recording]
