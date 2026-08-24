"""Compare two model IDs offline on the same versioned task dataset.

The scripted providers make this runnable without credentials. Replace those
providers and the client setup with configured providers to benchmark real
model IDs; the environment, dataset, reports, and trace sink stay the same.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _shared import ScriptedProvider, ensure_out_dir
from enroute import Benchmark, Enroute, Environment, JSONLSink, TaskData, TaskDataset


def make_env() -> Environment:
    """Create a fresh text-scoring environment for each benchmark job."""
    env = Environment(name="refund-quality", version="0.1.0")

    @env.scorer(name="mentions_refund")
    def mentions_refund(rollout: object) -> float:
        response = getattr(rollout, "response", None)
        text = getattr(response, "text", None) or ""
        return 1.0 if "refund" in text.lower() else 0.0

    return env


def main() -> None:
    out = ensure_out_dir()
    dataset = TaskDataset(
        name="refund-requests",
        version="0.1.0",
        tasks=[
            TaskData(task_id="refund-1", input="I need a refund."),
            TaskData(task_id="refund-2", input="Please reverse this purchase."),
        ],
    )
    client = Enroute(
        providers={
            "helpful": ScriptedProvider("helpful", "Your refund is approved."),
            "unhelpful": ScriptedProvider("unhelpful", "Please wait."),
        },
        sink=JSONLSink(out / "model-episodes.jsonl"),
        capture_content=True,
    )
    try:
        report = Benchmark(
            make_env(),
            models=["helpful/offline", "unhelpful/offline"],
            client=client,
            concurrency=2,
            environment_factory=make_env,
        ).run(dataset=dataset)
        markdown = report.to_markdown()
        print(markdown)
        (out / "report.md").write_text(markdown, encoding="utf-8")
        (out / "report.json").write_text(report.to_json(), encoding="utf-8")
    finally:
        client.close()


if __name__ == "__main__":
    main()
