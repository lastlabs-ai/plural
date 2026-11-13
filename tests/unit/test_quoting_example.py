"""Run the quoting example end to end with scripted models instead of real ones."""

from __future__ import annotations

import json
import os
import re
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

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "quoting"
CLI = Path(sys.executable).with_name("plural")
PRICE = re.compile(r"\$([\d,]+\.\d{2}) per short ton")
EARLIEST = re.compile(r"Earliest delivery for [\d.]+ short tons: (\d{4}-\d{2}-\d{2})")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _tasks() -> dict[str, dict[str, Any]]:
    """Each Task's answer key, requested date, and category, keyed by its instructions."""
    benchmark = yaml.safe_load((EXAMPLE / "benchmarks/quoting/benchmark.yaml").read_text())
    category = {name: item["id"] for item in benchmark["categories"] for name in item["tasks"]}
    tasks = {}
    for folder in sorted((EXAMPLE / "tasks").iterdir()):
        manifest = yaml.safe_load((folder / "task.yaml").read_text())
        instructions = (folder / "instruction.md").read_text().strip()
        tasks[instructions] = {
            "name": manifest["name"],
            "expected": manifest["expected"],
            "requested": DATE.search(instructions).group(0),  # type: ignore[union-attr]
            "category": category[manifest["name"]],
        }
    return tasks


TASKS = _tasks()


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


def _reply(policy: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """The next assistant message: ``reference`` answers right, ``weak`` acts like quote-bot."""
    request = next(message["content"] for message in messages if message["role"] == "user")
    task = next((value for key, value in TASKS.items() if key in str(request)), None)
    if task is None:
        return {"role": "assistant", "content": "Hello."}
    results = [str(message["content"]) for message in messages if message["role"] == "tool"]
    expected = task["expected"]
    if expected["decision"] == "handoff":
        if results:
            return {"role": "assistant", "content": "Passed to the sales team."}
        return _call("handoff", reason="The request needs a person to confirm it with you.")
    grade, tons = expected["grade"], expected["tons"]
    steps = ["lookup_price", "check_schedule"] if policy == "reference" else ["lookup_price"]
    if len(results) < len(steps):
        name = steps[len(results)]
        return _call(name, grade=grade) if name == "lookup_price" else _call(name, tons=tons)
    if len(results) > len(steps):
        return {"role": "assistant", "content": "Quote sent."}
    price = float(PRICE.search(results[0]).group(1).replace(",", ""))  # type: ignore[union-attr]
    date = task["requested"]
    if policy == "reference":
        date = max(date, EARLIEST.search(results[1]).group(1))  # type: ignore[union-attr]
    else:
        price = float(round(price))
    return _call(
        "submit_quote",
        grade=grade,
        tons=tons,
        price_per_ton=price,
        total_price=round(price * tons, 2),
        delivery_date=date,
        notes="Thanks for the request. Your quote is attached.",
    )


class _Model(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        message = _reply(self.path.split("/")[1], body["messages"])
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


@pytest.fixture(scope="module")
def model() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory, model: str) -> dict[str, dict[str, Any]]:
    """Run the Benchmark once per policy, and return each Trial's scores by policy and Task."""
    project = tmp_path_factory.mktemp("quoting") / "quoting"
    shutil.copytree(EXAMPLE, project)
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PLURAL_", "OPENAI_", "ANTHROPIC_"))
    }
    env.update(PLURAL_CONFIG_HOME=str(project.parent / "config"), QUOTING_MODEL_KEY="unused")
    output = {}
    for policy in ("reference", "weak"):
        agent = project / "agents" / policy
        agent.mkdir()
        (agent / "agent.yaml").write_text(
            f"name: {policy}\nversion: 1.0.0\nmodel: test/{policy}\ninstructions: Quote steel.\n"
            f"endpoint: {model}/{policy}/v1\nendpoint_key: QUOTING_MODEL_KEY\n",
            encoding="utf-8",
        )
        run = subprocess.run(
            [str(CLI), "run", "-b", "quoting", "-a", policy, "--yes", "--json"],
            cwd=project,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        job = json.loads(run.stdout)
        assert job["status"] == "succeeded"
        directory = project / ".plural/jobs" / job["job_id"]
        result = json.loads((directory / "result.json").read_text())
        output[policy] = {
            trial["receipt"]["task_pin"]["name"]: {
                "score": trial["score"],
                "state": json.loads(
                    (
                        directory
                        / "trials"
                        / trial["receipt"]["trial_id"]
                        / "executions/0/artifacts/state.json"
                    ).read_text()
                ),
                **trial["scores"],
            }
            for trial in result["trials"]
        }
    status = subprocess.run(
        [str(CLI), "eval", "status", "--json"],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    output["eval status"] = json.loads(status.stdout)
    output["eval status"]["latest_job"] = job["job_id"]
    return output


def test_the_reference_policy_answers_every_request_right(
    results: dict[str, dict[str, Any]],
) -> None:
    trials = results["reference"]
    assert len(trials) == 60
    assert {name: trial["score"] for name, trial in trials.items() if trial["score"] != 1.0} == {}


def test_quote_bots_planted_weaknesses_fail_where_they_should(
    results: dict[str, dict[str, Any]],
) -> None:
    by_name = {task["name"]: task for task in TASKS.values()}
    for name, trial in results["weak"].items():
        category = by_name[name]["category"]
        assert trial["quote-check.decision_correct"] == 1.0, name
        if category in {"ambiguous", "out-of-stock"}:
            assert trial["score"] == 1.0, name
            continue
        assert trial["quote-check.delivery_feasible"] == float(category == "simple"), name
        assert trial["quote-check.above_cost"] == 1.0, name
    rush = [name for name, task in by_name.items() if task["category"] == "rush"]
    assert all(results["weak"][name]["score"] == 0.0 for name in rush)
    quoted = {name: trial for name, trial in results["weak"].items() if trial["state"]["quote"]}
    assert len(quoted) == 40
    for name, trial in quoted.items():
        (price,) = trial["state"]["prices_given"].values()
        assert trial["quote-check.price_correct"] == float(price == round(price)), name


def test_eval_status_reads_the_baseline_from_the_latest_run(
    results: dict[str, dict[str, Any]],
) -> None:
    status = results["eval status"]
    job = status["latest_job"]
    steps = {step["title"]: step for step in status["steps"]}
    assert status["benchmark"] == "quoting"
    assert steps["Build the eval set"]["summary"].startswith("60 Tasks in 4 categories")
    assert steps["Baseline"]["status"] == "done"
    assert steps["Baseline"]["summary"].startswith(f"{job}: weak scored ")
    assert status["next_command"] == f"plural job show {job}"
