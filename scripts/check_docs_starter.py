"""Exercise the real Plural runner against a controlled model-transport fixture.

No model service is contacted. This verifies integration, not model quality.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from plural.execution.store import JobStore

SOURCE = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else Path(__file__).resolve().parents[1] / "examples" / "first-project"
)


class ModelFixture(BaseHTTPRequestHandler):
    """Serve predictable action choices for integration checks."""

    calls = 0
    wrong = False

    def log_message(self, *args):
        """Keep fixture request logs quiet."""
        pass

    def do_POST(self):
        """Return the next action for the current fixture task."""
        assert self.path == "/v1/chat/completions"
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert {t["function"]["name"] for t in request["tools"]} == {
            "inspect_ticket",
            "categorize",
            "draft_response",
            "resolve",
            # The Harness offers this so the Agent can end the episode itself.
            "finish",
        }
        task = json.loads(request["messages"][1]["content"])
        history = [m for m in request["messages"] if m["role"] == "tool"]
        if not history:
            name = "inspect_ticket"
            args = {}
        elif len(history) == 1:
            name = "categorize"
            args = {
                "category": "account"
                if self.wrong
                else {"ticket-1": "billing", "ticket-2": "technical", "ticket-3": "account"}[
                    task["task_info"]["ticket_id"]
                ]
            }
        elif len(history) == 2:
            name = "draft_response"
            args = {"message": "Thanks for contacting support. We will help with this request."}
        elif len(history) == 3:
            name = "resolve"
            args = {}
        else:
            name = None
            args = {}
        message = {"role": "assistant", "content": "Done."}
        if name:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call-{len(history)}",
                        "type": "function",
                        "function": {"name": "environment." + name, "arguments": json.dumps(args)},
                    }
                ],
            }
        self.__class__.calls += 1
        body = json.dumps(
            {
                "model": "fixture",
                "choices": [{"message": message}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(("127.0.0.1", 0), ModelFixture)
threading.Thread(target=server.serve_forever, daemon=True).start()
try:
    with tempfile.TemporaryDirectory(prefix="plural-docs-smoke-") as temp:
        root = Path(temp) / "first-project"
        shutil.copytree(SOURCE, root, ignore=shutil.ignore_patterns("__pycache__", ".plural"))
        env = {
            **os.environ,
            "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
            "OPENAI_API_KEY": "documentation-test-only",
            "OPENAI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
        }
        for key in ("PLURAL_GATEWAY_URL", "PLURAL_API_KEY"):
            env.pop(key, None)
        cli = Path(sys.executable).with_name("plural")

        def _run(*args):
            output = subprocess.run(
                [str(cli), *args], cwd=root, env=env, text=True, capture_output=True
            )
            if output.returncode:
                raise AssertionError(output.stdout + output.stderr)
            return output.stdout

        subprocess.run(
            [sys.executable, "build.py"], cwd=root, env=env, check=True, capture_output=True
        )
        for kind, path in [
            ("env", "environment"),
            ("task", "tasks/ticket-1.yaml"),
            ("verifier", "verifiers/correct.yaml"),
            ("agent", "agents/careful.yaml"),
            ("benchmark", "benchmark.yaml"),
        ]:
            _run(kind, "validate", path)
        plan = json.loads(_run("run", "job.yaml", "--dry-run"))
        assert plan["trial_count"] == 1
        result = json.loads(_run("run", "job.yaml", "--offline"))
        assert result["status"] == "succeeded", result
        assert result["trials"][0]["score"] == 1, result
        _run("job", "show", result["job_id"])
        _run("trial", "list", result["job_id"])
        suite = json.loads(
            _run(
                "run",
                "benchmark.yaml",
                "--agent",
                "agents/careful.yaml",
                "--agent",
                "agents/concise.yaml",
                "--offline",
            )
        )
        assert len(suite["trials"]) == 6 and all(t["score"] == 1 for t in suite["trials"]), suite
        ModelFixture.wrong = True
        # A changed instruction makes this a distinct Trial configuration.
        changed_job = yaml.safe_load((root / "job.yaml").read_text())
        changed_job["agents"][0]["instructions"] += " Inspect the result."
        (root / "job.yaml").write_text(yaml.safe_dump(changed_job, sort_keys=False))
        failed_quality = json.loads(_run("run", "job.yaml", "--offline"))
        assert failed_quality["trials"][0]["score"] == 0, failed_quality
        ModelFixture.wrong = False
        human = {
            "kind": "human",
            "name": "triage-review",
            "criteria": [
                {
                    "name": "fit",
                    "description": "The category matches the ticket.",
                    "min_score": 0,
                    "max_score": 2,
                }
            ],
            "weight": 0.5,
        }
        (root / "verifiers/review.yaml").write_text(yaml.safe_dump(human))
        task = yaml.safe_load((root / "tasks/ticket-1.yaml").read_text())
        task["verifiers"].append(human)
        (root / "tasks/review-case.yaml").write_text(yaml.safe_dump(task))
        _run(
            "job",
            "init",
            "review-job.yaml",
            "--source",
            "tasks/review-case.yaml",
            "--source-kind",
            "task",
            "--agent",
            "agents/careful.yaml",
        )
        pending = json.loads(_run("run", "review-job.yaml", "--offline"))
        assert pending["status"] == "awaiting_review", pending
        _run("review", "list", pending["job_id"])
        _run(
            "review",
            "submit",
            pending["job_id"],
            pending["trials"][0]["receipt"]["trial_id"],
            "--verifier",
            "triage-review",
            "--score",
            "2",
            "--feedback",
            "Verified fixture.",
        )
        done = json.loads(_run("job", "show", pending["job_id"]))
        stored = JobStore(root / ".plural/jobs").read_job_result(pending["job_id"])
        assert stored.status == "succeeded" and stored.trials[0].score == 1
        print(
            f"PASS: typed build, 5 validators, dry-run, native loop, 6-Trial benchmark, "
            f"zero-score case, local review completion ({ModelFixture.calls} controlled "
            f"model responses)."
        )
finally:
    server.shutdown()
    server.server_close()
