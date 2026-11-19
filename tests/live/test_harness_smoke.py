"""Every built-in Harness passes a Task that only writing a file can pass, through the gateway.

The check is deterministic and doesn't depend on the model: the Verifier reads
``smoke.txt`` and ignores the answer. Each run is recorded, so the gateway counts the
calls and tokens on that Trial execution's own key. Each Harness also reports its own
usage: the native loop in its ATIF trajectory, and each vendor CLI in its own output.
A Harness that reports more calls or output tokens than the gateway saw went around
it, and fails.

Run it with ``scripts/harness_smoke.sh``, which needs ``PLURAL_API_KEY`` and
``PLURAL_SMOKE_PROJECT``, the hosted project the key records into.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("PLURAL_RUN_HARNESS_SMOKE") != "1",
        reason="set PLURAL_RUN_HARNESS_SMOKE=1, or run scripts/harness_smoke.sh",
    ),
]

PROJECT = Path(__file__).parent / "harness_smoke"
CLI = Path(sys.executable).with_name("plural")
AGENTS = {
    "native": "smoke-native",
    "claude-code": "smoke-claude-code",
    "codex": "smoke-codex",
    "hermes": "smoke-hermes",
}


def _plural(root: Path, env: dict[str, str], *args: str) -> dict[str, Any]:
    done = subprocess.run(
        [str(CLI), *args], cwd=root, env=env, text=True, capture_output=True, timeout=900
    )
    assert done.returncode == 0, done.stdout[-4000:] + done.stderr[-4000:]
    return dict(json.loads(done.stdout)) if "--json" in args else {}


@pytest.fixture(scope="module")
def smoke(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    hosted = os.environ.get("PLURAL_SMOKE_PROJECT")
    if not os.environ.get("PLURAL_API_KEY") or not hosted:
        pytest.fail("set PLURAL_API_KEY and PLURAL_SMOKE_PROJECT")
    base = tmp_path_factory.mktemp("harness-smoke")
    root = base / "harness-smoke"
    shutil.copytree(PROJECT, root)
    # No provider key of this machine's may reach a run; the gateway key is the only one.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("OPENAI_", "ANTHROPIC_", "OPENROUTER_"))
    }
    env["PLURAL_CONFIG_HOME"] = str(base / "config")
    # Each night's copy is a new folder pushing to the same hosted project.
    _plural(root, env, "project", "push", "--connect", "--name", hosted, "--yes")
    return root, env


def _gateway_usage(
    env: dict[str, str], hosted_job: str, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Any]:
    from plural.cli.common import session, signed_in

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    studio = signed_in(session()).studio()
    (trial,) = studio.jobs.trials(hosted_job)
    return dict(studio.trials.gateway_usage(str(trial["execution_id"])))


def _reported(harness: str, artifacts: Path) -> tuple[int | None, int]:
    """The model calls, when known, and output tokens the Harness says it used."""
    if harness == "native":
        metrics = json.loads((artifacts / "atif-trajectory.json").read_text())["final_metrics"]
        return int(metrics["extra"]["llm_calls"]), int(metrics["total_completion_tokens"])
    (record,) = [
        json.loads(line)
        for line in (artifacts / "trajectory.jsonl").read_text().splitlines()
        if line.strip()
    ]
    if harness == "hermes":
        usage = record["usage"]
        assert usage["provider"] == "custom", usage
        return int(usage["api_calls"]), int(usage["output_tokens"])
    events = [
        json.loads(line)
        for line in str(record["stdout"]).splitlines()
        if line.strip().startswith("{")
    ]
    if harness == "claude-code":
        return None, sum(
            int(model["outputTokens"])
            for event in events
            if event.get("type") == "result"
            for model in (event.get("modelUsage") or {}).values()
        )
    return None, sum(
        int(event["usage"]["output_tokens"])
        for event in events
        if event.get("type") == "turn.completed"
    )


@pytest.mark.parametrize("harness", sorted(AGENTS))
def test_a_builtin_harness_writes_the_file_with_every_call_through_the_gateway(
    smoke: tuple[Path, dict[str, str]], harness: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, env = smoke
    run = _plural(
        root, env, "run", "-t", "write-file", "-a", AGENTS[harness], "--record", "--yes", "--json"
    )
    (trial,) = run["trials"]
    assert trial["status"] == "succeeded", trial["error"]
    assert trial["score"] == 1.0, f"{harness} did not write smoke.txt"
    assert run["recording_errors"] == [], run["recording_errors"]

    artifacts = next(
        Path(run["directory"]).glob(f"trials/{trial['trial_id']}/executions/*/artifacts")
    )
    calls, output_tokens = _reported(harness, artifacts)
    seen = _gateway_usage(env, run["hosted_job_id"], monkeypatch)
    assert seen["calls"] >= 1, f"the gateway saw no model call from {harness}"
    assert output_tokens >= 1, f"{harness} reported no output tokens"
    assert calls is None or calls <= seen["calls"], (
        f"{harness} made {calls} model call(s); the gateway saw {seen['calls']}"
    )
    assert output_tokens <= seen["completion_tokens"], (
        f"{harness} reported {output_tokens} output tokens; "
        f"the gateway saw {seen['completion_tokens']}"
    )
