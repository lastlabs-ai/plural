"""The native loop's own workspace tools, in an Environment with no Apps."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml

from plural.harness import native_runner
from plural.harness.packages import WORKSPACE_TOOLS, native_workspace_v1

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "bare-files"
CLI = Path(sys.executable).with_name("plural")
SEEN: list[list[str]] = []
JUDGED: list[dict[str, Any]] = []
HISTORIES: list[list[dict[str, Any]]] = []


def test_the_runner_offers_exactly_the_tools_the_package_declares() -> None:
    assert set(native_runner.WORKSPACE_TOOLS) == {tool.name for tool in WORKSPACE_TOOLS}
    assert native_workspace_v1().definition.tools == WORKSPACE_TOOLS


@pytest.mark.parametrize("provider", ["daytona", "docker"])
def test_a_bare_environment_gets_plural_and_an_app_host_on_a_remote_runtime(
    provider: str,
) -> None:
    from types import SimpleNamespace

    from plural import Environment, Runtime, Task
    from plural.execution.bootstrap import needs_plural
    from plural.execution.engine import TrialRunner
    from plural.verifiers import DeterministicVerifier, VerifierOutput

    task = Task(
        name="bare",
        instructions="Write a file.",
        environment=Environment(name="files", runtime=Runtime(provider=provider)),
        verifiers=[DeterministicVerifier(name="ok", check=lambda _: VerifierOutput(score=1.0))],
    ).definition()
    package = native_workspace_v1()
    # The native loop is a copied script, not Plural code, so Plural is installed only
    # because the Environment is bare and its episode needs a host to sign it.
    assert not needs_plural(task, package)
    for external, hosted in ((None, True), (object(), False)):
        runner = SimpleNamespace(task=task, agent=SimpleNamespace(external=external), environ={})
        runner._wants_host = lambda runner=runner: TrialRunner._wants_host(runner)
        remote = SimpleNamespace(name=provider)
        assert runner._wants_host() is hosted
        installed = TrialRunner._plural_distribution(runner, remote, package)  # type: ignore[arg-type]
        assert (installed is not None) is hosted


def _call(name: str, **arguments: Any) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": f"call_{name}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


class _Model(BaseHTTPRequestHandler):
    """Lists the files, reads the invoices, writes the total, then answers with it."""

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "response_format" in body:
            self._judge(body)
            return
        SEEN.append([tool["function"]["name"] for tool in body.get("tools") or []])
        HISTORIES.append(body["messages"])
        done = sum(message["role"] == "tool" for message in body["messages"])
        script = [
            _call("list_files", path=".."),
            _call("run", command="cat ../resources/*/invoices.csv"),
            _call("write_file", path="march-total.txt", content="5740.00"),
            {"role": "assistant", "content": "The March total is 5740.00."},
        ]
        self._reply({"choices": [{"message": script[min(done, len(script) - 1)]}]})

    def _judge(self, body: dict[str, Any]) -> None:
        JUDGED.append(json.loads(body["messages"][0]["content"]))
        verdict = {"scores": {"file": 1}, "evidence": ["march-total.txt"], "feedback": ""}
        self._reply({"choices": [{"message": {"content": json.dumps(verdict)}}]})

    def _reply(self, body: dict[str, Any]) -> None:
        payload = json.dumps({**body, "usage": {"prompt_tokens": 9, "completion_tokens": 3}})
        payload_bytes = payload.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload_bytes)))
        self.end_headers()
        self.wfile.write(payload_bytes)

    def log_message(self, *_args: object) -> None:
        return


@pytest.fixture
def model() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _project(tmp_path: Path, model: str) -> tuple[Path, dict[str, str]]:
    SEEN.clear()
    JUDGED.clear()
    HISTORIES.clear()
    project = tmp_path / "bare-files"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".plural", "__pycache__"))
    (project / "agents/files-native/agent.yaml").write_text(
        "name: files-native\nversion: 1.0.0\nmodel: test/script\ninstructions: Be exact.\n"
        f"endpoint: {model}/v1\nendpoint_key: SCRIPT_MODEL_KEY\n",
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PLURAL_", "OPENAI_", "ANTHROPIC_"))
    }
    env.update(PLURAL_CONFIG_HOME=str(tmp_path / "config"), SCRIPT_MODEL_KEY="unused")
    return project, env


def _run(project: Path, env: dict[str, str]) -> dict[str, Any]:
    run = subprocess.run(
        [str(CLI), "run", "-t", "march-total", "-a", "files-native", "--yes", "--json"],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    (trial,) = json.loads(run.stdout)["trials"]
    return dict(trial)


def test_the_native_loop_writes_the_file_in_a_bare_environment(tmp_path: Path, model: str) -> None:
    project, env = _project(tmp_path, model)
    trial = _run(project, env)
    assert trial["score"] == 1.0
    assert (trial["metrics"]["answer_correct"], trial["metrics"]["file_correct"]) == (1.0, 1.0)
    # Every model call of the episode offered the four tools; an earlier probe offers none.
    offered = [set(tools) for tools in SEEN if tools]
    assert offered and all(
        tools == {"read_file", "write_file", "list_files", "run"} for tools in offered
    )
    artifacts = next((project / ".plural/jobs").glob("*/trials/*/executions/0/artifacts"))
    steps = [json.loads(line) for line in (artifacts / "steps.jsonl").read_text().splitlines()]
    assert [(step["kind"], step["action"]) for step in steps] == [
        ("harness_tool", "list_files"),
        ("harness_tool", "run"),
        ("harness_tool", "write_file"),
    ]
    assert "INV-301" in json.dumps(steps[1]["observation"])
    # The host's private folder is never listed.
    assert ".plural" not in json.dumps(steps[0]["observation"])
    result = json.loads((artifacts.parent / "result.json").read_text())
    assert set(result["tools_offered"]) == {"read_file", "write_file", "list_files", "run"}


def test_a_fork_resumes_the_native_loop_after_its_workspace_tools(
    tmp_path: Path, model: str
) -> None:
    project, env = _project(tmp_path, model)
    trial = _run(project, env)
    artifacts = next((project / ".plural/jobs").glob("*/trials/*/executions/0/artifacts"))
    records = [json.loads(line) for line in (artifacts / "episode.jsonl").read_text().splitlines()]
    # Each tool call is recorded where it happened, with the call it answers.
    assert [record["kind"] for record in records if record["kind"] != "environment.reset"] == [
        "model.call",
        "environment.step",
        "model.call",
        "environment.step",
        "model.call",
        "environment.step",
        "model.call",
    ]
    assert [r["tool_call_id"] for r in records if r["kind"] == "environment.step"] == [
        "call_list_files",
        "call_run",
        "call_write_file",
    ]
    HISTORIES.clear()
    fork = subprocess.run(
        [
            *(str(CLI), "trial", "fork", str(trial["trial_id"]), "--step", "2"),
            *("--change", "message", "--payload", '{"text": "Write only the number."}'),
            *("--attempts", "1", "--json"),
        ],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert fork.returncode == 0, fork.stdout + fork.stderr
    assert json.loads(fork.stdout)["controls_reproduced"] == 1.0
    resumed = []
    for history in HISTORIES:
        called: list[str] = []
        for message in history:
            called.extend(call["id"] for call in message.get("tool_calls") or [])
            if message["role"] == "tool":
                assert message["tool_call_id"] in called, message
        resumed.append(called)
    # Each fork resumes after step 2, with no later call carried into its history.
    assert resumed.count(["call_list_files", "call_run"]) == 2


def _tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("PLURAL_SANDBOX_ROOT", str(tmp_path))
    (tmp_path / "workspace/environment").mkdir(parents=True)
    (tmp_path / "workspace/.plural-apps-x").mkdir()
    (tmp_path / "workspace/.plural-apps-x/secret.json").write_text("{}")
    environment = {"workspace": "/workspace/environment"}
    return native_runner._WorkspaceTools(environment, [{"capability": "shell", "reason": "no"}])


def _dispatch(tools: Any, name: str, **arguments: Any) -> str:
    outcome = tools.dispatch(_call(name, **arguments)["tool_calls"][0], deadline=1e12, turn=1)
    return str(outcome.message["content"])


def test_workspace_tools_stay_in_the_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = _tools(tmp_path, monkeypatch)
    assert _dispatch(tools, "write_file", path="out/a.txt", content="hi").startswith("Wrote 2")
    assert _dispatch(tools, "read_file", path="out/a.txt") == "hi"
    assert _dispatch(tools, "list_files", path="..") == "out/a.txt"
    assert "outside the workspace" in _dispatch(tools, "read_file", path="../../../etc/hosts")
    assert "not readable" in _dispatch(tools, "read_file", path="../.plural-apps-x/secret.json")
    # A denied capability is never offered.
    assert "run" not in {item["function"]["name"] for item in tools.declarations()}
    assert "unknown tool" in _dispatch(tools, "run", command="true")


_COMMAND_CHECK = """
import json
from plural.verifiers import Episode
episode = Episode.from_input()
found = episode.workspace.list("**/march-total.txt")
text = episode.workspace.read(found[0]).strip() if found else ""
json.dump(
    {"score": float(text == episode.expected["total_usd"]), "evidence": [f"read {text!r}"]},
    open("verifier-result.json", "w"),
)
"""


def test_command_and_judge_verifiers_read_the_same_workspace(tmp_path: Path, model: str) -> None:
    project, env = _project(tmp_path, model)
    command = project / "verifiers/file-command"
    command.mkdir()
    (command / "verifier.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "file-command",
                "version": "1.0.0",
                "kind": "deterministic",
                "check": [sys.executable, "-c", _COMMAND_CHECK],
            }
        ),
        encoding="utf-8",
    )
    judge = project / "verifiers/file-judge"
    judge.mkdir()
    (judge / "verifier.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "file-judge",
                "version": "1.0.0",
                "kind": "agent",
                "model": "openai/gpt-5.6-luna",
                "instructions": "Judge the file the Agent wrote.",
                "criteria": [{"name": "file", "description": "The file holds the total."}],
            }
        ),
        encoding="utf-8",
    )
    task = project / "tasks/march-total/task.yaml"
    task.write_text(
        task.read_text().replace(
            "  - total-check\n", "  - total-check\n  - file-command\n  - file-judge\n"
        ),
        encoding="utf-8",
    )
    env["PLURAL_GATEWAY_URL"] = f"{model}/v1"
    trial = _run(project, env)
    stored = next((project / ".plural/jobs").glob(f"*/trials/{trial['trial_id']}/result.json"))
    verdicts = json.loads(stored.read_text())["verifier_results"]
    results = {item["verifier_name"]: item for item in verdicts}
    # The command Verifier read march-total.txt through episode.workspace, in its own sandbox.
    assert results["file-command"]["score"] == 1.0
    assert results["file-command"]["evidence"] == ["read '5740.00'"]
    # The judge was shown the same file.
    (prompt,) = JUDGED
    shown = {item["name"]: item for item in prompt["evidence"]["workspace"]}
    assert shown["environment/march-total.txt"]["content"] == "5740.00"


_RESUME_HISTORIES: list[list[dict[str, Any]]] = []
_WRITTEN = threading.Event()
_RELEASE = threading.Event()


class _ResumeModel(BaseHTTPRequestHandler):
    """Writes a note, then hangs until its runner is killed; once resumed, reads the note."""

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _RESUME_HISTORIES.append(body["messages"])
        done = sum(message["role"] == "tool" for message in body["messages"])
        if done == 1 and not _WRITTEN.is_set():
            _WRITTEN.set()
            _RELEASE.wait(120)
            return
        script = [
            _call("write_file", path="note.txt", content="remember-42"),
            _call("read_file", path="note.txt"),
            {"role": "assistant", "content": "Done."},
        ]
        payload = json.dumps(
            {
                "choices": [{"message": script[min(done, len(script) - 1)]}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 3},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args: object) -> None:
        return


def test_a_resumed_trial_reads_the_file_it_wrote_before_its_run_checkpoint(
    tmp_path: Path,
) -> None:
    import signal
    import time

    _RESUME_HISTORIES.clear()
    _WRITTEN.clear()
    _RELEASE.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ResumeModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        project, env = _project(tmp_path, f"http://127.0.0.1:{server.server_address[1]}")
        environment = project / "environments/files/environment.yaml"
        environment.write_text(
            environment.read_text() + "\ncheckpoint_every:\n  steps: 1\n", encoding="utf-8"
        )
        runner = subprocess.Popen(
            [str(CLI), "run", "-t", "march-total", "-a", "files-native", "--yes", "--json"],
            cwd=project,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            assert _WRITTEN.wait(120), "the Agent never wrote its note"
            deadline = time.monotonic() + 60
            run: Path | None = None
            while time.monotonic() < deadline:
                run = next((project / ".plural/jobs").glob("*/trials/*/run"), None)
                if run is not None and (run / "workspace.bundle").is_file():
                    break
                time.sleep(0.5)
            assert run is not None and (run / "workspace.bundle").is_file()
        finally:
            os.killpg(runner.pid, signal.SIGKILL)
            runner.wait(30)
            _RELEASE.set()
        # As if the runner had been gone long enough to count as interrupted.
        state = json.loads((run / "journal.json").read_text())
        (run / "journal.json").write_text(json.dumps({**state, "updated": 0}))
        trial_id = run.parent.name

        resumed = subprocess.run(
            [str(CLI), "trial", "resume", trial_id, "--json"],
            cwd=project,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
        assert json.loads(resumed.stdout)["resumed"]["step"] == 1
        answers = [
            message["content"]
            for message in _RESUME_HISTORIES[-1]
            if message["role"] == "tool" and message.get("tool_call_id") == "call_read_file"
        ]
        assert answers == ["remember-42"]
    finally:
        _RELEASE.set()
        server.shutdown()
