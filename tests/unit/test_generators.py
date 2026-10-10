"""`plural env from-mcp|from-openapi|from-data|from-traces`, through the CLI."""

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
from plural.project.generators import from_mcp

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


def test_from_mcp_discovers_the_servers_tools(
    project: Project, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RECORDS_TOKEN", "records-secret")
    code, output, drafted = cli(
        "env",
        "from-mcp",
        "records-desk",
        "--command",
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
    assert records["name"] == "records_desk"
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

    code, output, _ = cli("env", "from-mcp", "records-desk", "--url", "https://x.dev/mcp")
    assert code != 0
    assert "already exist" in output


def test_from_mcp_keeps_the_draft_when_the_server_cannot_start(project: Project) -> None:
    code, output, drafted = cli(
        "env", "from-mcp", "broken", "--command", "plural-no-such-server", "--json"
    )

    assert code == 0, output
    assert drafted["apps"] == []
    assert drafted["problem"]
    assert (project.root / "environments/broken/environment.yaml").is_file()


def test_from_openapi_copies_the_document_and_lists_operations(
    project: Project,
    api: str,  # noqa: F811
) -> None:
    spec = project.root / "orders.json"
    spec.write_text(json.dumps({**SPEC, "servers": [{"url": api}]}))

    code, output, drafted = cli(
        "env",
        "from-openapi",
        "orders",
        "--spec",
        "orders.json",
        "--header",
        "Authorization=Bearer ${ORDERS_TOKEN}",
        "--json",
    )

    assert code == 0, output
    [orders] = drafted["apps"]
    assert orders["control"] == "live"
    assert {"name": "getOrder", "mutates_state": False} in orders["actions"]
    assert {"name": "createOrder", "mutates_state": True} in orders["actions"]
    assert (project.root / "environments/orders/orders.json").is_file()


def test_from_data_turns_files_into_tables(project: Project) -> None:
    (project.root / "customers.csv").write_text("id,name\n1,Ada\n2,Lin\n")
    (project.root / "tickets.jsonl").write_text('{"id": 1, "customer": 1, "open": true}\n')

    code, output, drafted = cli(
        "env", "from-data", "crm", "customers.csv", "tickets.jsonl", "--sql", "--json"
    )

    assert code == 0, output
    [crm] = drafted["apps"]
    assert crm["control"] == "owned"
    names = {item["name"] for item in crm["actions"]}
    assert {"list_customers", "update_tickets", "query"} <= names
    environment = Workspace(project).load(ResourceRef("environment", "crm")).value
    assert environment.definition().apps[0].kind == "data"


def test_from_traces_drafts_replay_apps_tasks_and_a_benchmark_the_traces_score_on(
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

    code, output, drafted = cli(
        "env", "from-traces", "support", "--traces", "traces.jsonl", "--json"
    )

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
    assert space.load(ResourceRef("verifier", "support-judge")).value.kind == "agent"

    from plural import Job

    job = Job.from_traces(traces, benchmark=space.load(ResourceRef("benchmark", "support")).value)
    assert [task.name for task in job.source.tasks] == ["support-t-1", "support-t-2"]


def test_a_reference_named_with_secret_stays_a_setup_secret() -> None:
    generated = from_mcp(
        "crm",
        app="crm",
        url="https://crm.example/mcp",
        headers={"Authorization": "Bearer ${CRM_TOKEN}", "X-Admin": "${CRM_ADMIN}"},
        secrets=["CRM_ADMIN"],
    )

    assert generated.credentials == ["CRM_TOKEN"]
    assert generated.secrets == ["CRM_ADMIN"]
    manifest = yaml.safe_load(generated.files["environments/crm/environment.yaml"])
    assert manifest["apps"][0]["mcp"]["credentials"] == ["CRM_TOKEN"]
    assert manifest["apps"][0]["mcp"]["secrets"] == ["CRM_ADMIN"]
