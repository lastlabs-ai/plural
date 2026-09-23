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


CATEGORIES = {"ticket-1": "billing", "ticket-2": "technical", "ticket-3": "account"}


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
        history = [m for m in request["messages"] if m["role"] == "tool"]
        if not history:
            name = "inspect_ticket"
            args = {}
        elif len(history) == 1:
            # Choose from what inspect_ticket showed, as a model would.
            ticket = history[0]["content"]
            name = "categorize"
            args = {
                "category": "account"
                if self.wrong
                else next(
                    category for ticket_id, category in CATEGORIES.items() if ticket_id in ticket
                )
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
            # Never read this machine's Plural sign-in.
            "PLURAL_CONFIG_HOME": str(Path(temp) / "config"),
        }
        for key in ("PLURAL_GATEWAY_URL", "PLURAL_API_KEY", "PLURAL_PROJECT", "PLURAL_PROFILE"):
            env.pop(key, None)
        cli = Path(sys.executable).with_name("plural")

        def _run(*args):
            output = subprocess.run(
                [str(cli), *args], cwd=root, env=env, text=True, capture_output=True
            )
            if output.returncode:
                raise AssertionError(output.stdout + output.stderr)
            return output.stdout

        for kind, name in [
            ("env", "support-queue"),
            ("task", "ticket-1"),
            ("verifier", "correct-category"),
            ("harness", "scripted-triage"),
            ("agent", "careful"),
            ("benchmark", "support-triage"),
        ]:
            _run(kind, "validate", name)
        plan = json.loads(_run("run", "-t", "ticket-1", "-a", "careful", "--dry-run", "--json"))
        assert len(plan["trials"]) == 1 and plan["harness"] == "native", plan
        assert not (root / ".plural" / "jobs").exists(), "a dry run must not create a Job"
        result = json.loads(_run("run", "-t", "ticket-1", "-a", "careful", "--json"))
        assert result["status"] == "succeeded", result
        assert result["trials"][0]["score"] == 1, result
        _run("job", "show", result["job_id"])
        _run("trial", "show", result["trials"][0]["trial_id"])
        suites = [
            json.loads(_run("run", "-b", "support-triage", "-a", agent, "--json"))
            for agent in ("careful", "concise")
        ]
        trials = [trial for suite in suites for trial in suite["trials"]]
        assert len(trials) == 6 and all(t["score"] == 1 for t in trials), suites
        ModelFixture.wrong = True
        failed_quality = json.loads(_run("run", "-t", "ticket-1", "-a", "careful", "--json"))
        assert failed_quality["trials"][0]["score"] == 0, failed_quality
        ModelFixture.wrong = False

        _run("verifier", "init", "triage-review")
        (root / "verifiers/triage-review/verify.py").unlink()
        (root / "verifiers/triage-review/verifier.yaml").write_text(
            yaml.safe_dump(
                {
                    "name": "triage-review",
                    "version": "0.1.0",
                    "kind": "human",
                    "criteria": [
                        {
                            "name": "fit",
                            "description": "The category matches the ticket.",
                            "min_score": 0,
                            "max_score": 2,
                        }
                    ],
                    "weight": 0.5,
                },
                sort_keys=False,
            )
        )
        shutil.copytree(root / "tasks/ticket-1", root / "tasks/review-case")
        task_file = root / "tasks/review-case/task.yaml"
        task = yaml.safe_load(task_file.read_text())
        task["name"] = "review-case"
        task["verifiers"].append("triage-review")
        task_file.write_text(yaml.safe_dump(task, sort_keys=False))
        pending = json.loads(_run("run", "-t", "review-case", "-a", "careful", "--json"))
        assert pending["status"] == "awaiting_review", pending
        waiting = json.loads(_run("review", "list", "--json"))
        trial_id = pending["trials"][0]["trial_id"]
        assert trial_id in json.dumps(waiting), waiting
        _run(
            "review",
            "submit",
            trial_id,
            "--verifier",
            "triage-review",
            "--score",
            "2",
            "--feedback",
            "Verified fixture.",
        )
        stored = JobStore(root / ".plural/jobs").read_job_result(pending["job_id"])
        assert stored.status == "succeeded" and stored.trials[0].score == 1, stored
        print(
            f"PASS: 6 validators, dry-run, native loop, 6-Trial benchmark, "
            f"zero-score case, local review completion ({ModelFixture.calls} controlled "
            f"model responses)."
        )
finally:
    server.shutdown()
    server.server_close()
