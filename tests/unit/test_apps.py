from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from plural import (
    App,
    Environment,
    Resource,
    Runtime,
    State,
    Step,
    action,
    initial,
)
from plural.apps import daemon
from plural.apps.definition import AppAction, AppDefinition, derive_control
from plural.apps.host import AppHost
from plural.apps.mcp import MCPError
from plural.environments.definition import EnvironmentDefinition

SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_records_server.py"


class Board(State):
    secret: str = initial("crane", pattern=r"^[a-z]{5}$")
    guesses: list[str] = []
    solved: bool = False


class Wordle(App[Board]):
    """Guess a five-letter word."""

    def reset(self, initial_state: Any) -> str:
        super().reset(initial_state)
        return "Guess the word. You have 6 guesses."

    @action
    def guess(self, word: str) -> str:
        """Guess a five-letter word."""
        if len(word) != 5:
            raise ValueError("a guess must have five letters")
        self.state.guesses.append(word)
        self.state.solved = word == self.state.secret
        return "solved" if self.state.solved else f"{6 - len(self.state.guesses)} guesses left"

    @action(read_only=True)
    def remaining(self) -> int:
        """How many guesses remain."""
        return 6 - len(self.state.guesses)

    def terminated(self) -> bool:
        return self.state.solved or len(self.state.guesses) >= 6


def solved(step: Step) -> float:
    """Two when the guess solves the puzzle, and a penalty for an invalid one."""
    if step.error:
        return -0.5
    return 2.0 * float(step.current_state["solved"] and not step.previous_state["solved"])


def notes_written(step: Step) -> float | None:
    """Reads another App, which a reward hook may do but never writes."""
    return float(len(step.apps["notes"].snapshot()["entries"])) if step.app == "wordle" else None


class Ledger(State):
    entries: list[str] = []


class Notes(App[Ledger]):
    @action
    def write(self, text: str) -> str:
        """Write a note."""
        self.state.entries.append(text)
        return "noted"


class Desk(Environment):
    def on_step(self, call, result, apps) -> None:
        del result
        if call.app == "wordle":
            apps["notes"].call("write", text=f"guessed {call.arguments['word']}")


class Scored(Environment):
    def on_step(self, call, result, apps) -> float | None:  # type: ignore[override]
        del result, apps
        return 0.5 if call.app == "wordle" else None


def test_single_app_environment_uses_bare_action_names() -> None:
    environment = Environment(apps=[Wordle()], runtime=Runtime.local())
    definition = environment.definition()
    assert definition.name == "wordle"
    assert [item.name for item in definition.actions] == ["guess", "remaining"]
    app = definition.apps[0]
    assert app.python == "test_apps.py:Wordle"
    assert app.control == "owned"
    assert app.description == "Guess a five-letter word."
    assert app.state_schema["properties"]["secret"]["x-plural-initial"] is True
    assert [item.mutates_state for item in app.actions] == [True, False]
    assert definition.reproducible


def test_wordle_episode_in_process() -> None:
    environment = Environment(apps=[Wordle()], runtime=Runtime.local())
    observation, _ = environment.reset(initial_state={"secret": "slate"}, verifiers=[solved])
    assert observation == {"text": "Guess the word. You have 6 guesses."}
    _, reward, terminated, _, info = environment.step("guess", word="toolong")
    assert info["error"] == "a guess must have five letters"
    assert (reward, terminated) == (-0.5, False)
    observation, reward, terminated, _, info = environment.step("guess", word="slate")
    assert observation == {"text": "solved"}
    assert reward == 2.0
    assert terminated
    assert info["rewards"][0]["name"] == "solved"
    report = environment.snapshot()
    assert report["wordle"]["initial"]["guesses"] == []
    assert report["wordle"]["final"]["solved"] is True


def test_invalid_arguments_are_feedback() -> None:
    environment = Environment(apps=[Wordle()], runtime=Runtime.local())
    environment.reset()
    _, _, _, _, info = environment.step("guess")
    assert "word" in info["error"]
    _, _, _, _, info = environment.step("missing")
    assert "unknown action 'missing'" in info["error"]


def test_several_apps_keep_their_tool_names_and_on_step_spans_them() -> None:
    environment = Desk(apps=[Wordle(), Notes()], runtime=Runtime.local(), name="desk")
    definition = environment.definition()
    assert [item.name for item in definition.actions] == ["guess", "remaining", "write"]
    assert definition.actions[0].description.startswith("[wordle] ")
    assert definition.python == "test_apps.py:Desk"
    observation, _ = environment.reset(
        initial_state={"wordle": {"secret": "crane"}}, verifiers=[solved, notes_written]
    )
    assert observation == {"text": "Guess the word. You have 6 guesses."}
    _, reward, _, _, info = environment.step("guess", word="slate")
    assert reward == 1.0
    assert [item["name"] for item in info["rewards"]] == ["solved", "notes_written"]
    assert info["effects"] == [
        {"app": "notes", "action": "write", "arguments": {"text": "guessed slate"}}
    ]
    assert environment.snapshot()["notes"]["final"]["entries"] == ["guessed slate"]


def test_initial_state_is_validated_per_app() -> None:
    environment = Environment(apps=[Wordle()], runtime=Runtime.local())
    with pytest.raises(ValueError):
        environment.reset(initial_state={"secret": 5})


def test_rebuilt_environment_matches_definition() -> None:
    environment = Desk(
        apps=[Wordle(), Notes()],
        runtime=Runtime.local(),
        name="desk",
        resources=(Resource(kind="data", name="words"),),
    )
    definition = environment.definition()
    restored = EnvironmentDefinition.model_validate_json(definition.model_dump_json())
    assert restored.content_hash == definition.content_hash
    rebuilt = Environment._from_definition(restored)
    assert type(rebuilt).__name__ == "Desk"
    rebuilt.reset(verifiers=[solved])
    _, reward, _, _, _ = rebuilt.step("guess", word="crane")
    assert reward == 2.0


def test_on_step_gives_no_rewards() -> None:
    environment = Scored(apps=[Wordle()], runtime=Runtime.local(), name="scored")
    environment.reset()
    with pytest.raises(TypeError, match="reward hook"):
        environment.step("guess", word="crane")


def test_a_failing_step_hook_never_fails_the_action() -> None:
    def broken(step: Step) -> float:
        raise RuntimeError("boom")

    environment = Environment(apps=[Wordle()], runtime=Runtime.local())
    environment.reset(verifiers=[broken, solved])
    observation, reward, _, _, info = environment.step("guess", word="crane")
    assert observation == {"text": "solved"}
    assert reward == 2.0
    assert info["rewards"][0]["error"].startswith("RuntimeError: boom (at test_apps.py:")


def test_tool_names_just_work_for_every_provider() -> None:
    def server(name: str, *tools: str, schema: dict[str, Any] | None = None) -> AppDefinition:
        return AppDefinition(
            name=name,
            kind="mcp",
            actions=tuple(
                AppAction(name=tool, parameters=schema or {"type": "object"}) for tool in tools
            ),
        )

    long = "x" * 80
    environment = EnvironmentDefinition(
        name="desk",
        apps=(
            server("crm", "search", "salesforce.query", "reset", long),
            server("docs", "search", "read file", schema={"$schema": "x", "properties": {}}),
        ),
    )
    exposed = {(item.app, item.action): item for item in environment.actions}
    assert exposed[("crm", "search")].name == "crm__search"
    assert exposed[("docs", "search")].name == "docs__search"
    assert exposed[("crm", "salesforce.query")].name == "salesforce_query"
    assert exposed[("crm", "reset")].name == "crm__reset"
    assert exposed[("docs", "read file")].name == "read_file"
    assert len(exposed[("crm", long)].name) == 64
    assert exposed[("docs", "read file")].parameters == {"type": "object", "properties": {}}
    assert exposed[("crm", "search")].parameters == {"type": "object", "properties": {}}
    alone = EnvironmentDefinition(name="crm", apps=(server("crm", "search", "salesforce.query"),))
    assert [item.name for item in alone.actions] == ["search", "salesforce_query"]
    assert alone.actions[0].description == ""


def test_environment_rejects_old_fields() -> None:
    with pytest.raises(ValueError, match="no longer owns"):
        EnvironmentDefinition.model_validate(
            {"name": "x", "actions": [{"name": "a"}], "runtime": {"provider": "local"}}
        )


def test_hooks_cannot_be_actions() -> None:
    class Broken(App[State]):
        @action
        def reset(self, initial_state: dict[str, Any]) -> None:  # type: ignore[override]
            del initial_state

    with pytest.raises(TypeError, match="App hook"):
        Broken().actions()


def test_app_settings_must_be_keywords() -> None:
    with pytest.raises(TypeError, match="keyword"):
        Wordle("wordle")  # type: ignore[misc]


def test_control_levels() -> None:
    assert derive_control("python", local=True, has_reset=True) == "owned"
    assert derive_control("mcp", local=False, has_reset=True) == "sandboxed"
    assert derive_control("mcp", local=False, has_reset=False) == "live"
    assert derive_control("replay", local=True, has_reset=True) == "replayed"


def test_app_names_and_secret_names_are_checked() -> None:
    with pytest.raises(ValueError):
        AppDefinition(name="Bad Name", kind="mcp")
    with pytest.raises(ValueError):
        AppDefinition(name="a__b", kind="mcp")
    with pytest.raises(ValueError):
        App.mcp("crm", url="https://example.com/mcp", secrets=["PATH"], actions=[])


def test_a_name_is_either_a_setup_secret_or_an_agent_credential() -> None:
    with pytest.raises(ValueError, match="both a secret and a credential"):
        AppDefinition(name="crm", kind="mcp", secrets=["CRM_TOKEN"], credentials=["CRM_TOKEN"])
    crm = AppDefinition(name="crm", kind="mcp", credentials=["CRM_TOKEN"])
    admin = AppDefinition(name="admin", kind="mcp", secrets=["CRM_TOKEN"])
    with pytest.raises(ValueError, match="secret of one App and a credential of another"):
        EnvironmentDefinition(name="desk", apps=(crm, admin))


def test_an_app_without_credentials_keeps_its_environment_hash() -> None:
    plain = EnvironmentDefinition(name="desk", apps=(AppDefinition(name="crm", kind="mcp"),))
    payload = plain.model_dump(mode="json")
    assert payload["apps"][0]["credentials"] == []
    needs = plain.model_copy(
        update={"apps": (AppDefinition(name="crm", kind="mcp", credentials=["CRM_TOKEN"]),)}
    )
    assert needs.content_hash != plain.content_hash
    assert needs.credentials[0].name == "CRM_TOKEN"
    assert plain.credentials == ()


def test_reset_and_snapshot_hooks_never_see_an_agents_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from plural.apps import mcp

    monkeypatch.setenv("CRM_TOKEN", "agent-token")
    monkeypatch.setenv("OTHER_TOKEN", "other-agent-token")
    monkeypatch.setenv("CRM_ADMIN", "admin-token")
    monkeypatch.setattr(mcp, "_hidden_from_hooks", frozenset())
    app = App.mcp(
        "crm",
        url="https://crm.example/mcp",
        headers={"Authorization": "${CRM_TOKEN}"},
        credentials=["CRM_TOKEN"],
        secrets=["CRM_ADMIN"],
        reset="python scripts/seed.py",
        actions=[],
    )
    mcp.hide_from_hooks(["OTHER_TOKEN"])
    hook = app._hook_environ()  # type: ignore[attr-defined]

    assert hook["CRM_ADMIN"] == "admin-token"
    assert "CRM_TOKEN" not in hook
    assert "OTHER_TOKEN" not in hook


# MCP Apps.


def _stdio_app(**settings: Any) -> App[Any]:
    return App.mcp("crm", command=[sys.executable, str(SERVER)], **settings)


def test_mcp_app_discovers_tools_and_read_only_hints() -> None:
    environment = Environment(apps=[_stdio_app()], runtime=Runtime.local())
    try:
        app = environment.definition().apps[0]
        assert [(item.name, item.mutates_state) for item in app.actions] == [
            ("create_record", True),
            ("get_record", False),
            ("list_records", False),
        ]
        assert app.kind == "mcp"
        assert app.control == "owned"
        assert app.python is None
        assert app.state_schema == {}
        assert "actions" not in app.config
    finally:
        environment.close()


def test_built_in_kinds_do_not_describe_an_app_with_their_docstring() -> None:
    assert App.mcp("crm", url="https://example.com/mcp", actions=[]).description == ""

    class Desk(App[Any]):
        """The support desk."""

    assert Desk().description == "The support desk."


def test_mcp_tool_filters() -> None:
    environment = Environment(
        apps=[_stdio_app(tools=["get_record", "create_record"], exclude=["create_record"])],
        runtime=Runtime.local(),
    )
    try:
        assert [item.name for item in environment.definition().actions] == ["get_record"]
    finally:
        environment.close()
    with pytest.raises(ValueError, match="does not offer: delete"):
        Environment(apps=[_stdio_app(tools=["delete"])], runtime=Runtime.local()).definition()


def test_mcp_episode_errors_are_feedback() -> None:
    environment = Environment(apps=[_stdio_app()], runtime=Runtime.local())
    try:
        environment.reset()
        observation, *_ = environment.step("create_record", name="Acme")
        assert observation == {"text": "created record 1"}
        _, _, _, _, info = environment.step("get_record", id="9")
        assert info["error"] == "no such record"
        observation, *_ = environment.step("list_records")
        assert observation == {"records": [{"id": "1", "name": "Acme"}]}
    finally:
        environment.close()


def test_a_project_secret_fills_a_setting_you_have_not_exported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from plural.apps.mcp import expand, use_credential_source, use_secret_source
    from plural.cli import secret_commands

    calls: list[list[str]] = []

    class Secrets:
        def resolve(self, names: list[str]) -> dict[str, Any]:
            calls.append(names)
            return {"environ": {"CRM_TOKEN": "stored"}} if names == ["CRM_TOKEN"] else {}

    class Studio:
        secrets = Secrets()

    monkeypatch.setattr(secret_commands, "_project_studio", lambda: (Studio(), "demo"))
    monkeypatch.delenv("CRM_TOKEN", raising=False)
    use_secret_source(secret_commands.project_secret_source())
    try:
        assert expand("Bearer ${CRM_TOKEN}") == "Bearer stored"
        assert expand("${CRM_TOKEN}") == "stored"
        assert calls == [["CRM_TOKEN"]]
        assert "CRM_TOKEN" not in os.environ
        with pytest.raises(MCPError, match="plural secret set OTHER_TOKEN"):
            expand("${OTHER_TOKEN}")
        assert expand("${CRM_TOKEN}", {"CRM_TOKEN": "exported"}) == "exported"

        # An Agent's credential never falls back to a project secret of the same name.
        calls.clear()
        with pytest.raises(MCPError, match="plural credential set"):
            expand("Bearer ${CRM_TOKEN}", credentials={"CRM_TOKEN"})
        assert calls == []

        # `plural run --agent` lets the planner reach the server with that Agent's own value.
        asked: list[str] = []
        use_credential_source(lambda name: asked.append(name) or "agent-token")
        try:
            assert expand("Bearer ${CRM_TOKEN}", credentials={"CRM_TOKEN"}) == "Bearer agent-token"
            with pytest.raises(MCPError, match="plural secret set OTHER_TOKEN"):
                expand("${OTHER_TOKEN}", credentials={"CRM_TOKEN"})
            assert asked == ["CRM_TOKEN"]
        finally:
            use_credential_source(None)

        def unreachable() -> Any:
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(secret_commands, "_project_studio", unreachable)
        use_secret_source(secret_commands.project_secret_source())
        with pytest.raises(MCPError, match="CRM_TOKEN is not set"):
            expand("${CRM_TOKEN}")
    finally:
        use_secret_source(None)


def test_mcp_command_server_gets_an_empty_folder_each_episode(tmp_path: Path) -> None:
    def episode() -> tuple[Any, Path]:
        environment = Environment(
            apps=[_stdio_app(env={"RECORDS_FILE": "${PLURAL_APP_DIR}/records.json"})],
            runtime=Runtime.local(),
        )
        try:
            environment.reset()
            before, *_ = environment.step("list_records")
            environment.step("create_record", name="Acme")
            folder = Path(environment.apps[0]._environ()["PLURAL_APP_DIR"])
            assert (folder / "records.json").exists()
        finally:
            environment.close()
        return before, folder

    first, first_folder = episode()
    second, second_folder = episode()
    assert first == second == {"records": []}
    assert first_folder != second_folder
    assert not first_folder.exists() and not second_folder.exists()


def test_mcp_server_crash_reports_its_output(tmp_path: Path) -> None:
    crash = tmp_path / "crash.py"
    crash.write_text(
        "import sys\nprint('missing CRM_URL', file=sys.stderr)\nsys.exit(3)\n", encoding="utf-8"
    )
    app = App.mcp("crm", command=[sys.executable, str(crash)])
    app.workspace = tmp_path
    output = r"(?s)exit code 3\. Its output is in .*server\.log.*CRM_URL"
    with pytest.raises(MCPError, match=output):
        app.actions()
    app.close()


def test_mcp_secrets_must_be_declared() -> None:
    with pytest.raises(ValueError, match="CRM_TOKEN"):
        App.mcp("crm", url="https://example.com/mcp", headers={"Authorization": "${CRM_TOKEN}"})


@pytest.fixture
def http_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("CRM_TOKEN", "token-value-xyz")
    process = subprocess.Popen(
        [sys.executable, str(SERVER), "--http", "0", "--require-token", "CRM_TOKEN"],
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, "CRM_TOKEN": "token-value-xyz"},
    )
    assert process.stdout is not None
    port = process.stdout.readline().strip()
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        process.kill()
        process.wait()


def test_mcp_over_http_with_secret_headers(
    http_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = App.mcp(
        "crm",
        url=http_server,
        headers={"Authorization": "Bearer ${CRM_TOKEN}"},
        secrets=["CRM_TOKEN"],
    )
    environment = Environment(apps=[app], runtime=Runtime.local())
    definition = environment.definition()
    assert definition.apps[0].control == "live"
    assert not definition.reproducible
    assert [item.name for item in definition.secrets] == ["CRM_TOKEN"]
    assert "token-value-xyz" not in definition.model_dump_json()
    environment.reset()
    observation, *_ = environment.step("create_record", name="Acme")
    assert observation == {"text": "created record 1"}
    environment.close()

    monkeypatch.setenv("CRM_TOKEN", "wrong")
    with pytest.raises(MCPError, match="401"):
        environment.reset()
    environment.close()


def test_mcp_reset_hook_makes_a_remote_app_sandboxed(tmp_path: Path) -> None:
    hook = tmp_path / "seed.py"
    hook.write_text("import sys, json; print('seeded', json.load(sys.stdin)['n'])\n")
    app = App.mcp(
        "crm",
        url="https://example.com/mcp",
        reset=[sys.executable, str(hook)],
        actions=[{"name": "noop", "description": "x"}],
    )
    assert app.resolved_control() == "sandboxed"
    app.workspace = tmp_path
    assert app._run(app.reset_command, stdin='{"n": 3}') == "seeded 3\n"  # type: ignore[attr-defined]


# The App host process.


WORKSPACE_SOURCE = """
from plural import App, Environment, State, action, initial


class Board(State):
    secret: str = initial("crane")
    solved: bool = False


class Wordle(App[Board]):
    @action
    def guess(self, word: str) -> str:
        \"\"\"Guess a word.\"\"\"
        self.state.solved = word == self.state.secret
        return "solved" if self.state.solved else "no"

    def terminated(self) -> bool:
        return self.state.solved

    def close(self) -> None:
        import time
        time.sleep(0.2)
        (self.workspace / "closed").write_text("yes")


class Desk(Environment):
    pass
"""

REWARD_SOURCE = """
def solved(step):
    crm = step.apps["crm"].query("list_records")
    return 2.0 * float(step.current_state["solved"]) + 0.5 * len(crm["records"])
"""


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Path]:
    from plural.environments.env import load_reference

    root = tmp_path / "environment"
    (root / ".plural" / "apps").mkdir(parents=True)
    (root / "desk.py").write_text(WORKSPACE_SOURCE)
    wordle = load_reference("desk.py:Wordle", root)
    desk = load_reference("desk.py:Desk", root)
    environment = desk(
        apps=[wordle(), _stdio_app()], runtime=Runtime.local(), name="desk", source=root
    )
    definition = environment.definition()
    environment.close()
    (root / ".plural/apps/environment.json").write_text(definition.model_dump_json())
    (root / ".plural/verifiers/won").mkdir(parents=True)
    (root / ".plural/verifiers/won/verify.py").write_text(REWARD_SOURCE)
    (root / ".plural/apps/task.json").write_text(
        json.dumps(
            {
                "initial_state": {"wordle": {"secret": "slate"}},
                "task": {"name": "t", "metadata": {}},
                "verifiers": [
                    {
                        "name": "won",
                        "version": "1.0.0",
                        "dir": ".plural/verifiers/won",
                        "python": "verify.py:solved",
                    }
                ],
            }
        )
    )
    yield root
    daemon.call("stop", root=root)


def _cli(root: Path, *args: str, stdin: str = "") -> Any:
    completed = subprocess.run(
        [sys.executable, "-m", "plural.apps.daemon", *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=root,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_app_host_keeps_state_across_action_commands(workspace: Path) -> None:
    opening = _cli(workspace, "reset")
    assert opening["protocol"] == "plural-step-v1"
    assert opening["kind"] == "reset"
    step = _cli(workspace, "step", "create_record", stdin='{"name": "Acme"}')
    assert step["app"] == "crm"
    assert step["rendered"] == "created record 1"
    step = _cli(workspace, "step", "guess", stdin='{"word": "slate"}')
    assert step["terminated"] is True
    assert "reward" not in step and "rewards" not in step
    listed = _cli(workspace, "query", "crm", "list_records")
    assert listed == {"records": [{"id": "1", "name": "Acme"}]}
    report = _cli(workspace, "finish")
    assert report["apps"]["wordle"]["final"]["solved"] is True
    assert report["apps"]["crm"]["control"] == "owned"
    guess = report["steps"][-1]
    assert guess["reward"] == 2.5
    assert guess["rewards"] == [{"name": "won", "version": "1.0.0", "app": "wordle", "value": 2.5}]
    assert (workspace / ".plural/apps/wordle/state.json").is_file()


def test_app_host_closes_apps_before_answering_stop(workspace: Path) -> None:
    daemon.call("reset", root=workspace)
    daemon.call("stop", root=workspace)
    assert (workspace / "closed").read_text() == "yes"


def test_app_host_refuses_queries_that_change_state(workspace: Path) -> None:
    daemon.call("reset", root=workspace)
    with pytest.raises(PermissionError, match="read-only"):
        daemon.call("query", root=workspace, app="wordle", action="guess", arguments={})


def test_app_host_reports_bad_arguments(workspace: Path) -> None:
    daemon.call("reset", root=workspace)
    step = _cli(workspace, "step", "guess", stdin="not json")
    assert step["info"]["error"] == "action arguments must be a JSON object"


def test_app_host_works_without_a_workspace_file(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="environment.json"):
        daemon.start(tmp_path)


def test_app_host_in_process_query() -> None:
    host = AppHost(Environment(apps=[Wordle()], runtime=Runtime.local()))
    host.reset()
    assert host.query("wordle", "remaining", {}) == 6


def test_app_host_numbers_steps_and_records_the_state_each_one_left(tmp_path: Path) -> None:
    host = AppHost(Environment(apps=[Wordle()], runtime=Runtime.local()), workspace=tmp_path)
    host.reset(initial_state={"wordle": {"secret": "slate"}})
    envelopes = [
        host.step("guess", {"word": "toolong"}),
        host.step("remaining", {}),
        host.step("guess", {"word": "slate"}),
    ]

    assert [item["info"]["step"] for item in envelopes] == [1, 2, 3]
    assert all("state" not in json.dumps(item["info"]) for item in envelopes)
    lines = [
        json.loads(line)
        for line in (tmp_path / ".plural/apps/states.jsonl").read_text().splitlines()
    ]
    assert [line["step"] for line in lines] == [0, 1, 2, 3]
    assert lines[0]["state"]["wordle"]["guesses"] == []
    assert lines[1]["error"] == "a guess must have five letters"
    assert lines[1]["state"] == lines[2]["state"] == {}
    assert lines[3]["state"]["wordle"]["solved"] is True
    assert lines[3]["action"] == "guess"


def test_a_private_host_keeps_state_off_disk_but_still_records_it(tmp_path: Path) -> None:
    host = AppHost(
        Environment(apps=[Wordle()], runtime=Runtime.local()),
        workspace=tmp_path,
        private_state=True,
    )
    host.reset(initial_state={"wordle": {"secret": "slate"}})
    host.step("guess", {"word": "crane"})

    apps = tmp_path / ".plural" / "apps"
    assert not (apps / "states.jsonl").exists()
    assert not (apps / "wordle" / "state.json").exists()
    # The Job still gets the State over the control socket, secret and all.
    states = host.recorded_states()
    assert states[0]["state"]["wordle"]["secret"] == "slate"
    assert states[-1]["state"]["wordle"]["guesses"] == ["crane"]


def test_a_controlled_host_lets_the_harness_act_but_not_read_or_restart(
    workspace: Path,
) -> None:
    daemon.start(workspace, token="job-only")
    try:
        assert daemon.call("reset", root=workspace)["kind"] == "reset"
        daemon.call("step", root=workspace, action="guess", arguments={"word": "crane"})
        for operation, fields in (
            ("hello", {}),
            ("finish", {}),
            ("stop", {}),
            ("query", {"app": "crm", "action": "list_records", "arguments": {}}),
        ):
            with pytest.raises(PermissionError, match="Only the Job"):
                daemon.call(operation, root=workspace, **fields)
            with pytest.raises(daemon.AppHostTampered):
                daemon.call(operation, root=workspace, token="guess", **fields)
        again = daemon.call("reset", root=workspace)
        assert again["info"]["error"] == "The episode has already started; it cannot be reset."
        report = daemon.call("finish", root=workspace, token="job-only")
        assert report["apps"]["wordle"]["final"]["solved"] is False
        assert report["states"][0]["state"]["wordle"]["secret"] == "slate"
        assert [step["action"] for step in report["steps"]] == ["guess"]
    finally:
        daemon.call("stop", root=workspace, token="job-only")
