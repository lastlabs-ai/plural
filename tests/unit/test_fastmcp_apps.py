from __future__ import annotations

import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

from plural import App, Environment, Runtime
from plural.apps.mcp import MCPApp

pytest.importorskip("fastmcp")

SERVER = textwrap.dedent(
    '''
    from fastmcp import FastMCP

    import plural.mcp

    mcp = FastMCP("desk")
    TICKETS: list[dict] = []


    @mcp.tool(annotations={"readOnlyHint": True})
    def list_tickets() -> dict:
        """List every ticket."""
        return {"tickets": TICKETS}


    @mcp.tool
    def close_ticket(id: str) -> str:
        """Close one ticket."""
        for ticket in TICKETS:
            if ticket["id"] == id:
                ticket["status"] = "closed"
                return f"closed {id}"
        raise ValueError(f"no ticket {id}")


    @mcp.tool(annotations={"readOnlyHint": True})
    def read_case() -> str:
        """Read the policy and this case's notes."""
        policy = (plural.mcp.environment_resources() / "policy.md").read_text()
        notes = plural.mcp.task_resources()
        case = (notes / "notes.md").read_text() if notes else "none"
        return f"{policy} | {case}"


    @plural.mcp.reset(mcp)
    def start(initial_state: dict) -> None:
        TICKETS[:] = [dict(item) for item in initial_state.get("tickets", [])]


    @plural.mcp.snapshot(mcp)
    def state() -> dict:
        return {"tickets": TICKETS}
    '''
)


@pytest.fixture
def desk(tmp_path: Path) -> Iterator[MCPApp]:
    (tmp_path / "server.py").write_text(SERVER)
    app = App.mcp("desk", server="server.py:mcp")
    app.workspace = tmp_path
    assert isinstance(app, MCPApp)
    yield app
    app.close()


def test_a_fastmcp_server_is_an_owned_app_with_hidden_hooks(desk: MCPApp) -> None:
    actions = {item.name: item for item in desk.actions()}
    assert set(actions) == {"list_tickets", "close_ticket", "read_case"}
    assert actions["list_tickets"].mutates_state is False
    assert actions["close_ticket"].mutates_state is True
    definition = desk.definition()
    assert definition.control == "owned"
    assert definition.has_reset and definition.has_snapshot
    assert definition.config == {
        "server": "server.py:mcp",
        "hooks": ["plural_reset", "plural_snapshot"],
    }

    assert desk.reset({"tickets": [{"id": "T-7", "status": "open"}]}) is None
    assert desk.call("close_ticket", {"id": "T-7"}) == "closed T-7"
    assert desk.snapshot() == {"tickets": [{"id": "T-7", "status": "closed"}]}
    with pytest.raises(ValueError, match="unknown action 'plural_snapshot'"):
        desk.call("plural_snapshot", {})


def test_the_server_reads_both_resource_volumes(
    desk: MCPApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "resources"
    (root / "environment-resources").mkdir(parents=True)
    (root / "task-resources").mkdir()
    (root / "environment-resources" / "policy.md").write_text("refunds under $50")
    (root / "task-resources" / "notes.md").write_text("customer is upset")
    monkeypatch.setenv("PLURAL_RESOURCES_DIR", str(root))
    desk.reset({})
    assert desk.call("read_case", {}) == "refunds under $50 | customer is upset"


def test_a_rebuilt_app_knows_its_hooks_without_listing(desk: MCPApp, tmp_path: Path) -> None:
    environment = Environment(name="desk", apps=[desk], runtime=Runtime.local(), source=tmp_path)
    definition = environment.definition()
    rebuilt = Environment._from_definition(definition)
    app = rebuilt.apps[0]
    assert isinstance(app, MCPApp)
    assert app._hooks == frozenset({"plural_reset", "plural_snapshot"})
    rebuilt.close()


def test_exactly_one_way_to_reach_the_server() -> None:
    with pytest.raises(ValueError, match="exactly one of server"):
        App.mcp("desk", server="server.py:mcp", url="https://example.com/mcp")


def test_a_server_acting_on_an_outside_system_is_not_owned(tmp_path: Path) -> None:
    (tmp_path / "server.py").write_text(SERVER)
    lake = App.mcp("lake", server="server.py:mcp", remote=True)
    lake.workspace = tmp_path
    assert lake.definition().control == "sandboxed"
    assert lake.definition().config["remote"] is True
    lake.close()
    bare = tmp_path / "bare.py"
    bare.write_text(
        "from fastmcp import FastMCP\nmcp = FastMCP('lake')\n\n"
        "@mcp.tool\ndef query(sql: str) -> str:\n    return sql\n"
    )
    live = App.mcp("lake", server="bare.py:mcp", remote=True)
    live.workspace = tmp_path
    assert live.definition().control == "live"
    live.close()


def test_serve_over_http_defaults_to_port_3825() -> None:
    import plural.mcp
    from plural.mcp import serve

    calls: list[dict[str, object]] = []

    class Server:
        def run(self, **kwargs: object) -> None:
            calls.append(kwargs)

    serve.serve_http(Server())
    assert plural.mcp.PORT == 3825
    assert calls == [
        {
            "transport": "http",
            "host": "127.0.0.1",
            "port": 3825,
            "path": "/mcp",
            "show_banner": False,
        }
    ]


def test_env_serve_answers_an_mcp_client_over_http(tmp_path: Path) -> None:
    import socket
    import subprocess
    import sys
    import time

    from plural.apps.mcp import MCPClient, MCPError

    project = tmp_path / "demo"
    (project / "environments" / "desk").mkdir(parents=True)
    (project / "project.yaml").write_text("name: demo\n")
    (project / "environments" / "desk" / "server.py").write_text(SERVER)
    (project / "environments" / "desk" / "environment.yaml").write_text(
        "name: desk\napps:\n  - name: desk\n    mcp:\n      server: server.py:mcp\n"
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, "-c", "from plural.cli import main; main()", "env", "serve", "desk"]
        + ["--port", str(port)],
        cwd=project,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        client = None
        for _ in range(100):
            try:
                client = MCPClient(url=f"http://127.0.0.1:{port}/mcp", timeout_seconds=5)
                break
            except MCPError:
                time.sleep(0.1)
        assert client is not None, process.stdout.read() if process.stdout else ""
        names = {tool["name"] for tool in client.list_tools()}
        assert {"list_tickets", "close_ticket", "read_case"} <= names
        client.close()
    finally:
        process.terminate()
        process.wait(timeout=10)
