"""Executable checks for canonical documentation and examples."""

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

import pytest

from plural import Job
from plural.project import Project, Workspace
from plural.project.runs import RunRequest, plan_run

ROOT = Path(__file__).resolve().parents[2]
CLI = Path(sys.executable).with_name("plural")
TUTORIALS = {
    "first-project": ("support-triage", "scripted"),
    "wordle": ("wordle", "luna"),
}


def _run(*command: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.fixture
def isolated(tmp_path: Path) -> dict[str, str]:
    """An environment with no stored login and no model credentials."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PLURAL_", "OPENAI_", "ANTHROPIC_"))
    }
    env["PLURAL_CONFIG_HOME"] = str(tmp_path / "config")
    return env


def test_canonical_docs_metadata_links_nav_terms_and_snippets() -> None:
    """Keep the authored docs contract aligned with navigation and public APIs."""
    output = _run(sys.executable, "scripts/check_docs.py")
    assert "internal links are valid" in output


@pytest.mark.parametrize("directory", sorted(TUTORIALS))
def test_tutorial_projects_validate_and_dry_run(directory: str, isolated: dict[str, str]) -> None:
    root = ROOT / "examples" / directory
    benchmark, agent = TUTORIALS[directory]
    for path in sorted(root.rglob("*.py")):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")

    _run(str(CLI), "benchmark", "validate", benchmark, cwd=root, env=isolated)
    plan = json.loads(
        _run(
            str(CLI),
            "run",
            "-b",
            benchmark,
            "-a",
            agent,
            "--dry-run",
            "--json",
            cwd=root,
            env=isolated,
        )
    )
    assert plan["source"] == f"benchmark/{benchmark}"
    assert plan["location"] == "local"
    assert plan["trials"]
    assert not (root / ".plural").exists()


GUESSES = ("crane", "slate", "audio", "point", "storm", "heart")


class _WordleModel(BaseHTTPRequestHandler):
    """An OpenAI-compatible model that guesses GUESSES in order, one per reply."""

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        played = sum(message["role"] == "tool" for message in body["messages"])
        message: dict[str, object] = {"role": "assistant", "content": "Out of words."}
        if played < len(GUESSES):
            arguments = json.dumps({"word": GUESSES[played]})
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call_{played}",
                        "type": "function",
                        "function": {"name": "guess", "arguments": arguments},
                    }
                ],
            }
        payload = json.dumps(
            {
                "choices": [{"message": message}],
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


@pytest.fixture
def wordle_model() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _WordleModel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()


def test_wordle_runs_a_model_and_records_its_messages(
    tmp_path: Path, isolated: dict[str, str], wordle_model: str
) -> None:
    project = tmp_path / "wordle"
    shutil.copytree(ROOT / "examples" / "wordle", project)
    agent = project / "agents" / "scripted"
    agent.mkdir()
    (agent / "agent.yaml").write_text(
        "name: scripted\nversion: 1.0.0\nmodel: test/wordle\ninstructions: Play Wordle.\n"
        f"endpoint: {wordle_model}\nendpoint_key: WORDLE_MODEL_KEY\n",
        encoding="utf-8",
    )
    env = {**isolated, "WORDLE_MODEL_KEY": "unused"}
    job = json.loads(
        _run(str(CLI), "run", "-b", "wordle", "-a", "scripted", "--json", cwd=project, env=env)
    )
    assert job["status"] == "succeeded"
    scores = {trial["task"]: trial["score"] for trial in job["trials"]}
    assert scores == {"crane": 1.0, "slate": 1.0, "point": 1.0, "storm": 1.0, "nymph": 0.0}

    artifacts = (project / ".plural" / "jobs").glob("*/trials/*/executions/0/artifacts")
    (storm,) = [
        path
        for path in artifacts
        if json.loads((path / "state.json").read_text(encoding="utf-8"))["secret"] == "storm"
    ]
    transcript = json.loads((storm / "trajectory.json").read_text(encoding="utf-8"))
    assert set(transcript) >= {"messages", "status", "time_elapsed", "finalized"}
    roles = [message["role"] for message in transcript["messages"]]
    assert roles[:2] == ["system", "user"]
    assert roles.count("tool") == 5
    assert "storm" not in json.dumps(transcript["messages"][:2])


@pytest.mark.parametrize("directory", sorted(TUTORIALS))
def test_python_sdk_and_cli_plan_the_same_job(directory: str) -> None:
    benchmark, agent = TUTORIALS[directory]
    workspace = Workspace(Project.find(ROOT / "examples" / directory))

    from_python = Job(workspace.get("benchmark", benchmark), agents=[workspace.get("agent", agent)])
    from_cli = plan_run(workspace, RunRequest(benchmark=benchmark, agent=agent))

    unnumbered = from_cli.spec.model_copy(update={"run_id": None})
    assert unnumbered.content_hash == from_python.spec.content_hash
    assert len(from_cli.job.plan.trials) == len(from_python.plan.trials)


def test_audited_documentation_limits_remain_explicit() -> None:
    runtime = (ROOT / "docs/project/environments.md").read_text(encoding="utf-8")
    reviews = (ROOT / "docs/running/reviews.md").read_text(encoding="utf-8")
    integrations = (ROOT / "docs/reference/integrations.md").read_text(encoding="utf-8")
    fields = (ROOT / "docs/reference/fields.md").read_text(encoding="utf-8")
    api = (ROOT / "docs/reference/api.md").read_text(encoding="utf-8")
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    assert "nothing secret is saved with the Environment" in runtime
    assert "does not expose the full contracted evidence view" in reviews
    assert "native APIs are not directly executed by Job" in integrations
    assert "post-resolution Pydantic constructor models" in fields
    assert "public `Job` constructor is omitted" in fields
    assert "\n## plural.execution.JobRunner\n" not in api
    assert "\n## plural.jobs.JobSpec\n" not in api
    assert "\n## plural.jobs.TrialSpec\n" not in api
    assert "- project/*.md" not in mkdocs
    assert "- running/*.md" not in mkdocs


def test_support_tutorial_integration() -> None:
    """Run the documented starter against a controlled model transport."""
    output = _run(sys.executable, "scripts/check_docs_starter.py")
    assert "PASS:" in output
