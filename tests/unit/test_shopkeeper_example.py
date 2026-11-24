"""Run the shopkeeper example with a scripted model: a running metric, no final answer.

The scripted shopkeeper stocks up, then opens the shop day after day until the
season ends. It never writes a final answer, so the Trial is judged only on
what the App host measured and the books in State, by shop-books' gate.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import yaml

from plural.metrics import MetricSpec, judge

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "shopkeeper"
CLI = Path(sys.executable).with_name("plural")
OPENING = (("buy", {"item": "coffee", "units": 40}), ("buy", {"item": "bagel", "units": 20}))


def _reply(messages: list[dict[str, Any]]) -> dict[str, Any]:
    results = [str(message["content"]) for message in messages if message["role"] == "tool"]
    if len(results) < len(OPENING):
        name, arguments = OPENING[len(results)]
    else:
        name, arguments = "wait", {}
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"call_{len(results)}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


class _Model(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        payload = json.dumps(
            {
                "choices": [{"message": _reply(body["messages"])}],
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
def season(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One season of shop-001 under the shopkeeper Benchmark, by the scripted shopkeeper."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    project = tmp_path_factory.mktemp("shopkeeper") / "shopkeeper"
    try:
        shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".plural", "__pycache__"))
        path = project / "benchmarks/shopkeeper/benchmark.yaml"
        benchmark = yaml.safe_load(path.read_text())
        benchmark["tasks"] = ["shop-001"]
        path.write_text(yaml.safe_dump(benchmark, sort_keys=False), encoding="utf-8")
        agent = project / "agents" / "scripted"
        agent.mkdir()
        (agent / "agent.yaml").write_text(
            "name: scripted\nversion: 1.0.0\nmodel: test/scripted\n"
            "instructions: Run the shop.\n"
            f"endpoint: http://127.0.0.1:{server.server_address[1]}/v1\n"
            "endpoint_key: SHOP_MODEL_KEY\n",
            encoding="utf-8",
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("PLURAL_", "OPENAI_", "ANTHROPIC_"))
        }
        env.update(PLURAL_CONFIG_HOME=str(project.parent / "config"), SHOP_MODEL_KEY="unused")
        run = subprocess.run(
            [str(CLI), "run", "-b", "shopkeeper", "-a", "scripted", "--yes", "--json"],
            cwd=project,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        job = json.loads(run.stdout)
        directory = project / ".plural/jobs" / job["job_id"]
        result = json.loads((directory / "result.json").read_text())
        (trial,) = result["trials"]
        artifacts = directory / "trials" / trial["receipt"]["trial_id"] / "executions/0/artifacts"
        return {
            "job": job,
            "result": result,
            "trial": trial,
            "artifacts": artifacts,
            "project": project,
            "env": env,
        }
    finally:
        server.shutdown()


def test_the_running_metric_is_sampled_after_every_action(season: dict[str, Any]) -> None:
    points = [
        json.loads(line)
        for line in (season["artifacts"] / "metrics.jsonl").read_text().splitlines()
        if line.strip()
    ]
    cash = [point for point in points if "cash_on_hand" in point["values"]]
    # Two purchases, then fourteen days open.
    assert len(cash) == len(OPENING) + 14
    assert [point["step"] for point in cash] == list(range(1, len(cash) + 1))
    assert all(point["source"] == "agent" for point in cash)
    assert cash[-1]["sim_time"] == 15.0
    assert season["trial"]["metrics"]["cash_on_hand"] == cash[-1]["values"]["cash_on_hand"]


def test_the_verifier_gate_judges_a_trial_with_no_final_answer(season: dict[str, Any]) -> None:
    trial = season["trial"]
    state = json.loads((season["artifacts"] / "state.json").read_text())
    harness = json.loads((season["artifacts"] / "result.json").read_text())
    assert harness["stop_reason"] == "environment_terminated"
    assert not harness["response"]
    assert trial["status"] == "succeeded"
    assert set(trial["gates"]) == {"never_negative_cash"}
    assert trial["passed"] is (state["lowest_cash"] >= 0)
    (aggregate,) = season["result"]["aggregates"]
    assert aggregate["primary_metric"] == "cash_on_hand"
    assert aggregate["primary"] == trial["metrics"]["cash_on_hand"]
    assert aggregate["pass_rate"] == float(trial["passed"])


def test_running_metrics_alone_gate_without_an_answer() -> None:
    """Constraint C5: every metric running and no answer still yields gates."""
    specs = [
        MetricSpec(
            name="cash_on_hand", kind="running", aggregate="final", gate=True, target=">= 0"
        ),
        MetricSpec(name="cash_on_hand_peak", kind="running", aggregate="max"),
    ]
    assert judge(specs, {"cash_on_hand": 512.0}).passed is True
    assert judge(specs, {"cash_on_hand": -3.0}).gates == {"cash_on_hand": False}
    # No applicable gate: the Trial is not judged, never a vacuous pass.
    assert judge(specs, {"cash_on_hand": None}).passed is None


def test_the_run_summary_ranks_on_the_running_metric_and_shows_the_pass_rate(
    season: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    from plural.cli.run_commands import _print_result
    from plural.jobs import JobResult
    from plural.metrics import in_unit

    result = JobResult.model_validate(season["result"])
    passed = "100%" if season["trial"]["passed"] else "0%"
    _print_result("job_1", result)
    line = capsys.readouterr().out.splitlines()[1]
    assert line.startswith("  scripted: cash_on_hand ")
    assert line.endswith(f"; pass rate {passed} (passed every gate)")
    # The success rate counts scores at the threshold; the pass rate counts gates.
    summary = {"agent_name": "scripted", "text": "score 0.43, success rate 0%, over 1 Task"}
    _print_result("job_1", result, [summary])
    line = capsys.readouterr().out.splitlines()[1]
    cash = season["trial"]["metrics"]["cash_on_hand"]
    spec = result.aggregates[0].metrics["cash_on_hand"]
    # In the metric's unit and direction, not as a bare number.
    assert line == (
        f"  scripted: cash_on_hand {in_unit(cash, spec.unit)} (over 1 of 1, "
        f"{spec.direction} is better), score 0.43, success rate 0%, "
        f"over 1 Task; pass rate {passed} (passed every gate)"
    )


def test_verifier_apply_stores_the_measured_points_once(season: dict[str, Any]) -> None:
    """``verifier apply`` keeps measure's points, with the clocks the run recorded."""
    path = season["artifacts"] / "metrics.jsonl"
    live = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def apply() -> dict[str, Any]:
        run = subprocess.run(
            [
                str(CLI),
                "verifier",
                "apply",
                "shop-books",
                "--job",
                season["job"]["job_id"],
                "--json",
            ],
            cwd=season["project"],
            env=season["env"],
            text=True,
            capture_output=True,
            check=False,
        )
        assert run.returncode == 0, run.stdout + run.stderr
        return json.loads(run.stdout)  # type: ignore[no-any-return]

    (first,) = apply()["trials"]
    stored = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert first["metric_points"] == len(live) == len(stored)
    assert {point["version"] for point in stored} == {"1.1.0"}
    assert [(p["step"], p["values"], p["sim_time"]) for p in stored] == [
        (p["step"], p["values"], p["sim_time"]) for p in live
    ]
    (again,) = apply()["trials"]
    assert again["metric_points"] == 0
