from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from plural import App
from plural.apps.mcp import MCPApp

pytest.importorskip("fastmcp")


@pytest.fixture
def volumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "resources"
    shared = root / "environment-resources" / "resources"
    task = root / "task-resources" / "resources"
    shared.mkdir(parents=True)
    task.mkdir(parents=True)
    (shared / "policy.md").write_text("# Refunds\nRefunds under $50 need no approval.\n")
    (shared / "orders.csv").write_text("id,customer,total\n1,acme,40\n2,globex,75.5\n")
    (task / "ticket.json").write_text(json.dumps([{"id": "T-7", "order": 2}]))
    (task / "orders.csv").write_text("id,customer,total\n9,initech,12\n")
    with sqlite3.connect(shared / "crm.sqlite") as connection:
        connection.execute("CREATE TABLE accounts (id INTEGER, name TEXT)")
        connection.execute("INSERT INTO accounts VALUES (1, 'Acme')")
    monkeypatch.setenv("PLURAL_RESOURCES_DIR", str(root))
    return root


def _app(tmp_path: Path, server: str) -> MCPApp:
    app = App.mcp("files", server=server)
    assert isinstance(app, MCPApp)
    app.workspace = tmp_path
    return app


@pytest.fixture
def files(tmp_path: Path, volumes: Path) -> Iterator[MCPApp]:
    app = _app(tmp_path, "plural.mcp.files:server")
    app.reset({})
    yield app
    app.close()


def test_the_agent_reads_both_volumes_without_changing_them(files: MCPApp) -> None:
    actions = {item.name: item for item in files.actions()}
    assert set(actions) == {"list_files", "read_file", "search_files", "list_tables", "query"}
    assert not any(item.mutates_state for item in actions.values())
    assert files.definition().control == "owned"

    assert files.call("list_files", {}) == "environment-resources/\ntask-resources/"
    listing = files.call("list_files", {"path": "task-resources", "recursive": True})
    assert "task-resources/resources/ticket.json" in listing
    policy = files.call("read_file", {"path": "environment-resources/resources/policy.md"})
    assert policy == "# Refunds\nRefunds under $50 need no approval."
    found = files.call("search_files", {"pattern": "approval", "glob": "*.md"})
    assert (
        found == "environment-resources/resources/policy.md:2: Refunds under $50 need no approval."
    )
    with pytest.raises(ValueError, match="outside"):
        files.call("read_file", {"path": "environment-resources/../../etc"})


def test_a_planted_link_never_leads_outside_the_folders(tmp_path: Path, volumes: Path) -> None:
    secret = tmp_path / "host-private.txt"
    secret.write_text("control-token\n")
    shared = volumes / "environment-resources" / "resources"
    (shared / "notes.txt").symlink_to(secret)
    (shared / "elsewhere").symlink_to(tmp_path, target_is_directory=True)
    app = _app(tmp_path, "plural.mcp.files:server")
    try:
        app.reset({})
        listing = app.call("list_files", {"path": "environment-resources", "recursive": True})
        assert "notes.txt" not in listing and "elsewhere" not in listing
        assert app.call("search_files", {"pattern": "control-token"}) == "No matches."
        for path in ("resources/notes.txt", "resources/elsewhere/host-private.txt"):
            with pytest.raises(ValueError, match="outside"):
                app.call("read_file", {"path": f"environment-resources/{path}"})
        with pytest.raises(ValueError, match="longer than"):
            app.call("search_files", {"pattern": "a" * 501})
    finally:
        app.close()


def test_tables_are_queryable_and_read_only(files: MCPApp) -> None:
    tables = {item["table"]: item for item in files.call("list_tables", {})["tables"]}
    assert set(tables) == {
        "environment_resources_orders",
        "task_resources_orders",
        "ticket",
        "crm.accounts",
    }
    assert tables["ticket"]["file"] == "task-resources/resources/ticket.json"
    result = files.call(
        "query",
        {"sql": "SELECT customer, total FROM environment_resources_orders WHERE total > 50"},
    )
    assert result["rows"] == [{"customer": "globex", "total": 75.5}]
    assert files.call("query", {"sql": "SELECT name FROM crm.accounts"})["rows"] == [
        {"name": "Acme"}
    ]
    with pytest.raises(ValueError, match="Only SELECT"):
        files.call("query", {"sql": "DELETE FROM ticket"})


def test_the_writable_server_writes_only_to_scratch(tmp_path: Path, volumes: Path) -> None:
    app = _app(tmp_path, "plural.mcp.files:writable")
    try:
        app.reset({})
        assert "write_file" in {item.name for item in app.actions()}
        assert app.definition().has_snapshot
        with pytest.raises(ValueError, match="Only scratch/"):
            app.call("write_file", {"path": "environment-resources/x.md", "content": "no"})
        app.call("write_file", {"path": "scratch/notes/summary.md", "content": "refund 40"})
        assert app.call("read_file", {"path": "scratch/notes/summary.md"}) == "refund 40"
        assert app.snapshot() == {"scratch": {"notes/summary.md": "refund 40"}}
        assert not (volumes / "environment-resources" / "x.md").exists()
    finally:
        app.close()
