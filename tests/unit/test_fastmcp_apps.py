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
