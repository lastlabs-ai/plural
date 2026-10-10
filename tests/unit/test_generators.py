"""`plural env add|eject-files`, through the CLI."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from project_fixtures import write_project
from test_app_kinds import SPEC, api  # noqa: F401
from typer.testing import CliRunner

from plural.cli.main import app
from plural.project import Project, ResourceRef, Workspace
from plural.project.generators import add_app, app_name, mcp_app

SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_records_server.py"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: Path) -> Project:
    created = write_project(tmp_path / "desk")
    monkeypatch.chdir(created.root)
    return created


def cli(*args: str) -> tuple[int, str, Any]:
    result = CliRunner().invoke(app, list(args))
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        raise result.exception
    payload = json.loads(result.stdout) if "--json" in args and result.exit_code == 0 else None
    return result.exit_code, result.output, payload


def test_add_mcp_creates_the_environment_and_discovers_the_servers_tools(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RECORDS_TOKEN", "records-secret")
    code, output, drafted = cli(
        "env",
        "add",
        "records-desk",
        "--mcp",
        f"{sys.executable} {SERVER}",
        "--env",
        "RECORDS_TOKEN=${RECORDS_TOKEN}",
        "--tool",
        "get_record",
        "--tool",
        "list_records",
        "--json",
    )

    assert code == 0, output
    assert drafted["problem"] is None
    [records] = drafted["apps"]
    assert records["name"] == "records"
    assert [item["name"] for item in records["actions"]] == ["get_record", "list_records"]
    assert records["secrets"] == []
    assert records["credentials"] == [
        {"name": "RECORDS_TOKEN", "required": True, "description": ""}
    ]
    assert "records-secret" not in output
    manifest = yaml.safe_load(
        (project.root / "environments/records-desk/environment.yaml").read_text()
    )
    assert manifest["apps"][0]["mcp"]["credentials"] == ["RECORDS_TOKEN"]
    assert "secrets" not in manifest["apps"][0]["mcp"]
    readme = (project.root / "environments/records-desk/README.md").read_text()
    assert "RECORDS_TOKEN" in readme
    assert "plural agent credential set" in readme

    code, output, _ = cli("env", "add", "records-desk", "--mcp", "https://records.dev/mcp")
    assert code != 0
    assert "already has an App named records" in output


def test_add_extends_an_environment_and_keeps_what_is_there(project: Project) -> None:
    manifest_path = project.root / "environments/queue/environment.yaml"
    code, output, added = cli(
        "env",
        "add",
        "queue",
        "--mcp",
        "https://mcp.linear.app/mcp",
        "--header",
        "Authorization=Bearer ${LINEAR_TOKEN}",
        "--json",
    )

    assert code == 0, output
    assert added["updated"] is True
    assert "Added App linear." in added["notes"]
    text = manifest_path.read_text()
    assert text.startswith("# Queue environment.")
    manifest = yaml.safe_load(text)
    assert manifest["python"] == "environment.py:Queue"
    assert manifest["apps"] == [
        {
            "name": "linear",
            "mcp": {
                "url": "https://mcp.linear.app/mcp",
                "headers": {"Authorization": "Bearer ${LINEAR_TOKEN}"},
                "credentials": ["LINEAR_TOKEN"],
            },
        }
    ]
    readme = (project.root / "environments/queue/README.md").read_text()
    assert "`linear` is an MCP server reached at https://mcp.linear.app/mcp" in readme

    code, output, _ = cli(
        "env", "add", "queue", "--mcp", "https://x.dev/mcp", "--runtime", "docker"
    )
    assert code != 0 and "runs on local" in output


def test_add_takes_exactly_one_source(project: Project) -> None:
    code, output, _ = cli("env", "add", "desk")
    assert code != 0 and "Give one system to add" in output
    code, output, _ = cli("env", "add", "desk", "--mcp", "x", "--openapi", "y.json")
    assert code != 0 and "Give one system to add" in output


@pytest.mark.parametrize(
    ("source", "name"),
    [
        ("https://mcp.linear.app/mcp", "linear"),
        ("https://api.example.com/v1/crm.yaml", "example"),
        ("npx -y @modelcontextprotocol/server-memory", "memory"),
        ("uvx mcp-server-git --repository .", "git"),
        ("npx github-mcp-server@latest", "github"),
        ("specs/orders.json", "orders"),
        ("python server.py", "desk"),
    ],
)
def test_app_names_come_from_the_source(source: str, name: str) -> None:
    assert app_name(source, fallback="desk") == name


def test_add_mcp_keeps_the_files_when_the_server_cannot_start(project: Project) -> None:
    code, output, drafted = cli("env", "add", "broken", "--mcp", "plural-no-such-server", "--json")

    assert code == 0, output
    assert drafted["apps"] == []
    assert drafted["problem"]
    assert (project.root / "environments/broken/environment.yaml").is_file()


def test_add_openapi_copies_the_document_and_lists_operations(
    project: Project,
    api: str,  # noqa: F811
) -> None:
    spec = project.root / "orders.json"
    spec.write_text(json.dumps({**SPEC, "servers": [{"url": api}]}))

    code, output, drafted = cli(
        "env",
        "add",
        "orders",
        "--openapi",
        "orders.json",
        "--header",
        "Authorization=Bearer ${ORDERS_TOKEN}",
        "--json",
    )

    assert code == 0, output
    [orders] = drafted["apps"]
    assert orders["name"] == "orders"
    assert orders["control"] == "live"
    assert {"name": "getOrder", "mutates_state": False} in orders["actions"]
    assert {"name": "createOrder", "mutates_state": True} in orders["actions"]
    assert (project.root / "environments/orders/orders.json").is_file()


def test_eject_files_copies_the_ready_made_server_to_edit(project: Project) -> None:
    code, output, _ = cli("env", "init", "desk")
    assert code == 0, output

    code, output, ejected = cli("env", "eject-files", "desk", "--json")

    assert code == 0, output
    assert ejected == {
        "file": "environments/desk/files_server.py",
        "server": "files_server.py:server",
    }
    source = (project.root / "environments/desk/files_server.py").read_text()
    assert "def list_files" in source and "def query" in source
    code, output, _ = cli("env", "eject-files", "desk")
    assert code != 0 and "already exists" in output


def test_add_traces_drafts_replay_apps_tasks_and_a_benchmark_the_traces_score_on(
    project: Project,
) -> None:
    def trace(ticket: str, order: str) -> dict[str, Any]:
        return {
            "id": ticket,
            "model": "acme/support",
            "messages": [
                {"role": "user", "content": f"Is order {order} refundable?"},
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "function": {
                                "name": "orders__get",
                                "arguments": json.dumps({"id": order}),
                            },
                        },
                        {"id": "c2", "function": {"name": "policy", "arguments": "{}"}},
                    ],
                },
                {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"id": order})},
                {"role": "tool", "tool_call_id": "c2", "content": "Refunds within 30 days."},
                {"role": "assistant", "content": "Yes."},
            ],
        }

    traces = project.root / "traces.jsonl"
    traces.write_text(json.dumps(trace("T-1", "A")) + "\n" + json.dumps(trace("T-2", "B")) + "\n")

    code, output, drafted = cli("env", "add", "support", "--traces", "traces.jsonl", "--json")

    assert code == 0, output
    assert drafted["problem"] is None
    assert {item["name"]: item["control"] for item in drafted["apps"]} == {
        "orders": "replayed",
        "tools": "replayed",
    }
    assert drafted["tasks"] == ["support-t-1", "support-t-2"]
    task = yaml.safe_load((project.root / "tasks/support-t-1/task.yaml").read_text())
    assert task["metadata"] == {"trace_id": "T-1"}
    assert (project.root / "tasks/support-t-1/instruction.md").read_text() == (
        "Is order A refundable?\n"
    )
    space = Workspace(project)
    assert len(space.load(ResourceRef("benchmark", "support")).value.tasks) == 2
    assert space.load(ResourceRef("rewarder", "support-judge")).value.kind == "agent"


def _call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}


def _tool(name: str, description: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {"id": {"type": "string"}}},
        },
    }


def _ticket(ticket: str, calls: list[str], tools: list[dict[str, Any]]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [{"role": "user", "content": f"Handle ticket {ticket}."}]
    for index, name in enumerate(calls):
        messages.append(
            {"role": "assistant", "tool_calls": [_call(f"c{index}", name, {"id": ticket})]}
        )
        messages.append({"role": "tool", "tool_call_id": f"c{index}", "content": f"{name} ok"})
    messages.append({"role": "assistant", "content": "Done."})
    return {"id": ticket, "messages": messages, "tools": tools}


def test_add_traces_offers_the_agents_own_tools_with_their_descriptions(
    project: Project,
) -> None:
    tools = [
        _tool("crm__lookup", "Find a customer by id."),
        _tool("crm__note", "Add a note to a customer."),
    ]
    (project.root / "traces.jsonl").write_text(
        json.dumps(_ticket("T-1", ["crm__lookup"], tools)) + "\n"
    )

    code, output, drafted = cli("env", "add", "desk", "--traces", "traces.jsonl", "--json")

    assert code == 0, output
    [crm] = drafted["apps"]
    assert [action["name"] for action in crm["actions"]] == ["lookup", "note"]
    environment = Workspace(project).load(ResourceRef("environment", "desk")).value
    app = next(item for item in environment.apps if item.name == "crm")
    described = {action.name: action.description for action in app.actions()}
    assert described == {"lookup": "Find a customer by id.", "note": "Add a note to a customer."}
    with pytest.raises(ValueError, match="never called it"):
        app.call("note", {"id": "T-1"})


def test_add_traces_again_adds_new_tools_systems_and_tasks(project: Project) -> None:
    old_tools = [_tool("crm__lookup", "Find a customer."), _tool("crm__note", "Add a note.")]
    first = [
        _ticket("T-1", ["crm__lookup"], old_tools),
        _ticket("T-2", ["crm__lookup", "crm__note"], old_tools),
    ]
    (project.root / "first.jsonl").write_text("".join(json.dumps(t) + "\n" for t in first))
    code, output, _ = cli("env", "add", "desk", "--traces", "first.jsonl", "--json")
    assert code == 0, output

    new_tools = [
        _tool("crm__lookup", "Find a customer by id or email."),
        _tool("crm__note", "Add a note."),
        _tool("crm__refund", "Refund an order."),
        _tool("crm__escalate", "Hand the ticket to a person."),
        _tool("billing__invoice", "Read an invoice."),
    ]
    second = [
        _ticket("T-2", ["crm__lookup", "crm__note"], new_tools),
        _ticket("T-3", ["crm__lookup", "crm__refund", "billing__invoice"], new_tools),
        _ticket("T-4", ["crm__escalate"], new_tools),
    ]
    (project.root / "second.jsonl").write_text("".join(json.dumps(t) + "\n" for t in second))
    code, output, updated = cli("env", "add", "desk", "--traces", "second.jsonl", "--json")

    assert code == 0, output
    assert updated["updated"] is True
    assert updated["problem"] is None
    assert updated["tasks"] == ["desk-t-3", "desk-t-4"]
    notes = "\n".join(updated["notes"])
    assert "Skipped 1 trace(s) already imported." in notes
    assert "App crm: 2 new action(s): escalate, refund" in notes
    assert "updated description or schema: lookup" in notes
    assert "New App billing: 1 action(s), 1 recorded call(s)." in notes
    actions = {app["name"]: [a["name"] for a in app["actions"]] for app in updated["apps"]}
    assert actions == {
        "billing": ["invoice"],
        "crm": ["lookup", "note", "refund", "escalate"],
    }
    space = Workspace(project)
    benchmark = space.load(ResourceRef("benchmark", "desk")).value
    assert [task.name for task in benchmark.tasks] == [
        "desk-t-1",
        "desk-t-2",
        "desk-t-3",
        "desk-t-4",
    ]
    manifest = (project.root / "environments/desk/environment.yaml").read_text()
    assert manifest.startswith("# Drafted by `plural env add`")
    recordings = (project.root / "environments/desk/apps/crm/recordings.jsonl").read_text()
    assert len(recordings.splitlines()) == 6

    code, output, again = cli("env", "add", "desk", "--traces", "second.jsonl", "--json")
    assert code == 0, output
    assert again["tasks"] == []
    assert "Nothing new to add." in again["notes"]


def test_add_traces_drafts_tasks_that_cover_every_tool_first(project: Project) -> None:
    traces = [_ticket(f"T-{index}", ["lookup"], []) for index in range(1, 6)]
    traces.append(_ticket("T-6", ["refund"], []))
    (project.root / "traces.jsonl").write_text("".join(json.dumps(t) + "\n" for t in traces))

    code, output, drafted = cli(
        "env", "add", "desk", "--traces", "traces.jsonl", "--max-tasks", "2", "--json"
    )

    assert code == 0, output
    assert drafted["tasks"] == ["desk-t-1", "desk-t-6"]


def test_a_reference_named_with_secret_stays_a_setup_secret(tmp_path: Path) -> None:
    draft = mcp_app(
        "crm",
        url="https://crm.example/mcp",
        headers={"Authorization": "Bearer ${CRM_TOKEN}", "X-Admin": "${CRM_ADMIN}"},
        secrets=["CRM_ADMIN"],
    )
    generated = add_app(tmp_path, "crm", draft)

    assert generated.credentials == ["CRM_TOKEN"]
    assert generated.secrets == ["CRM_ADMIN"]
    manifest = yaml.safe_load(generated.files["environments/crm/environment.yaml"])
    assert manifest["apps"][0]["mcp"]["credentials"] == ["CRM_TOKEN"]
    assert manifest["apps"][0]["mcp"]["secrets"] == ["CRM_ADMIN"]
