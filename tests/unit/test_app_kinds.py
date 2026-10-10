from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from plural import App, Environment, Runtime
from plural.apps.data import DataApp
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
    with pytest.raises(ValueError, match="list them in secrets"):
        OpenAPIApp(name="orders", spec="orders.json", headers={"X-Key": "${HIDDEN_KEY}"})


def _shop(tmp_path: Path, **settings: Any) -> Environment:
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data/customers.csv").write_text("id,name,credit\n1,Ada,12.5\n2,Lin,0\n")
    (tmp_path / "data/orders.json").write_text(
        json.dumps([{"id": 10, "customer": 1, "total": 30}, {"id": 11, "customer": 2, "total": 5}])
    )
    app = App.data(
        "shop",
        tables={"customers": "data/customers.csv", "orders": "data/orders.json"},
        **settings,
    )
    return Environment(apps=[app], runtime=Runtime.local(), source=tmp_path)


def test_data_app_generates_actions_and_keeps_the_source_unchanged(tmp_path: Path) -> None:
    environment = _shop(tmp_path, read_only=["customers"], sql=True)
    definition = environment.definition()
    names = {item.name: item for item in definition.actions}
    assert set(names) == {
        "list_customers",
        "get_customers",
        "list_orders",
        "get_orders",
        "create_orders",
        "update_orders",
        "delete_orders",
        "query",
    }
    assert names["query"].mutates_state is False
    assert definition.apps[0].control == "owned"

    environment.reset(initial_state={"orders": [{"id": 1, "customer": 1, "total": 99}]})
    observation, *_ = environment.step("list_orders")
    assert observation["rows"] == [{"id": 1, "customer": 1, "total": 99}]
    observation, *_ = environment.step("create_orders", customer=2, total=7)
    assert observation == {"id": 2, "customer": 2, "total": 7}
    environment.step("update_orders", id=2, values={"total": 8})
    environment.step("delete_orders", id=1)
    observation, *_ = environment.step("get_customers", id=1)
    assert observation == {"id": 1, "name": "Ada", "credit": 12.5}
    _obs, _r, _t, _u, info = environment.step("query", sql="DELETE FROM orders")
    assert "readonly" in info["error"] or "read-only" in info["error"]
    observation, *_ = environment.step("query", sql="SELECT count(*) AS n FROM orders")
    assert observation["rows"] == [{"n": 1}]
    _obs, _r, _t, _u, info = environment.step("get_orders", id=1)
    assert "no row" in info["error"]
    assert environment.apps[0].snapshot()["orders"] == [{"id": 2, "customer": 2, "total": 8}]
    environment.close()
    assert "Ada" in (tmp_path / "data/customers.csv").read_text()
    assert json.loads((tmp_path / "data/orders.json").read_text())[0]["total"] == 30


def test_data_app_initial_state_is_validated_per_table(tmp_path: Path) -> None:
    from plural import DeterministicVerifier, Episode, Task, VerifierOutput

    def check(episode: Episode) -> VerifierOutput:
        return VerifierOutput(score=1)

    environment = _shop(tmp_path)
    with pytest.raises(ValueError, match="does not define: 'refunds'"):
        Task(
            name="seeded",
            instructions="Refund.",
            environment=environment,
            verifiers=[DeterministicVerifier(name="ok", check=check)],
            initial_state={"refunds": []},
        )


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


def test_data_app_needs_a_source() -> None:
    with pytest.raises(ValueError, match="needs database or tables"):
        DataApp(name="empty")


def test_environment_yaml_lists_apps_of_every_connected_kind(
    tmp_path: Path, api: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import textwrap

    from project_fixtures import write_project

    from plural.project import ResourceRef, Workspace

    project = write_project(tmp_path / "desk")
    folder = project.root / "environments/backoffice"
    (folder / "data").mkdir(parents=True)
    (folder / "data/customers.csv").write_text("id,name\n1,Ada\n")
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
                data:
                  tables:
                    customers: data/customers.csv
                  secrets: [CRM_EXPORT_TOKEN]
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
    assert "orders__getOrder" in {item.name for item in definition.actions}
    assert "crm__create_customers" in {item.name for item in definition.actions}
    assert "payments__refund" in {item.name for item in definition.actions}

    from typer.testing import CliRunner

    from plural.cli.main import app

    monkeypatch.chdir(project.root)
    monkeypatch.delenv("CRM_EXPORT_TOKEN", raising=False)
    result = CliRunner().invoke(app, ["env", "validate", "backoffice", "--json"])
    assert result.exit_code == 0, result.output
    summary = {item["name"]: item for item in json.loads(result.output)["apps"]}
    assert summary["crm"]["secrets"] == [
        {"name": "CRM_EXPORT_TOKEN", "required": True, "set": False}
    ]
    assert {"name": "getOrder", "mutates_state": False} in summary["orders"]["actions"]
