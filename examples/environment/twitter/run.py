"""Run the reply-to-mentions task with a small offline policy."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import ensure_out_dir
from enroute import JSONLSink, TraceWriter
from enroute.tracing import ParsedAction
from enroute.types import ChatRequest
from examples.environment.twitter.env import make_env


class ReplyPolicy:
    """View notifications, then reply to each returned mention id."""

    def __init__(self) -> None:
        self.mention_ids: list[str] | None = None
        self.replies = 0

    def act(self, request: ChatRequest, **_: object) -> ParsedAction:
        if self.mention_ids is None:
            mention_ids = _mention_ids(request)
            if not mention_ids:
                return ParsedAction(name="view_notifications")
            self.mention_ids = mention_ids
        if self.replies >= len(self.mention_ids):
            raise RuntimeError("reply task did not terminate after all mentions")
        post_id = self.mention_ids[self.replies]
        self.replies += 1
        return ParsedAction(
            name="reply",
            arguments={"post_id": post_id, "text": "Thanks for the mention!"},
        )


def _mention_ids(request: ChatRequest) -> list[str]:
    for message in reversed(request.messages):
        if message.role == "tool" and message.name == "view_notifications" and message.content:
            payload = json.loads(message.content)
            return [str(item["post_id"]) for item in payload.get("mentions", [])]
    return []


def main() -> None:
    out = ensure_out_dir()
    env = make_env()
    task = next(env.iter_tasks())
    rollout = env.run_episode(task, ReplyPolicy(), model="reply-policy")
    trace = rollout.trace
    writer = TraceWriter(JSONLSink(out / "twitter.jsonl"))
    try:
        writer.record(trace)
    finally:
        writer.close()
    print(f"environment={trace.environment}@{trace.environment_version}")
    print(f"fingerprint={trace.environment_fingerprint}")
    print(f"reward={trace.outcome.reward if trace.outcome else None}")
    print(f"terminated={trace.terminated} truncated={trace.truncated}")
    print(f"metrics={trace.metrics}")
    for i, step in enumerate(trace.steps, start=1):
        if step.type != "decision":
            continue
        actions = ", ".join(a.name for a in step.parsed_action) or "respond"
        reward = sum(e.value for e in step.reward_events)
        print(f"  decision {i}: {actions}  step_reward={reward}")
    print(f"transitions={len(trace.transitions())}")


if __name__ == "__main__":
    main()
