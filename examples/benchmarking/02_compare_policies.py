"""Compare two deterministic policies on the real LibraryEnv."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.environment.library.env import make_env

from _shared import ensure_out_dir
from enroute import Benchmark, JSONLSink, TaskDataset, TraceWriter
from enroute.tracing import ParsedAction
from enroute.types import ChatRequest


class ResearchPolicy:
    """Search, read, and answer using the question in the request."""

    def __init__(self) -> None:
        self.step = 0
        self.query = ""
        self.doc_id = ""
        self.answer = ""

    def act(self, request: ChatRequest, **_: object) -> ParsedAction:
        if self.step == 0:
            prompt = "\n".join(message.content or "" for message in request.messages).lower()
            if "cortado" in prompt:
                self.query, self.doc_id, self.answer = "cortado", "d2", "Grove"
            elif "voting" in prompt:
                self.query, self.doc_id, self.answer = "voting", "d1", "the river path"
            else:
                raise ValueError("unsupported library question")
            action = ParsedAction(name="search", arguments={"query": self.query})
        elif self.step == 1:
            action = ParsedAction(name="read", arguments={"doc_id": self.doc_id})
        else:
            action = ParsedAction(name="answer", arguments={"text": self.answer})
        self.step += 1
        return action


class ImmediateGuessPolicy:
    """Skip research and submit the same wrong answer."""

    def act(self, request: ChatRequest, **_: object) -> ParsedAction:
        del request
        return ParsedAction(name="answer", arguments={"text": "I don't know"})


def main() -> None:
    out = ensure_out_dir()
    env = make_env()
    dataset = TaskDataset(
        name="library-defaults",
        version=env.version,
        tasks=list(env.iter_tasks()),
    )
    writer = TraceWriter(JSONLSink(out / "policy-episodes.jsonl"))
    try:
        report = Benchmark.from_policies(
            env,
            {
                "researcher": ResearchPolicy,
                "guesser": ImmediateGuessPolicy,
            },
            concurrency=4,
            environment_factory=make_env,
            trace_writer=writer,
        ).run(dataset=dataset)
    finally:
        writer.close()

    markdown = report.to_markdown()
    print(markdown)
    (out / "policy-report.md").write_text(markdown, encoding="utf-8")
    (out / "policy-report.json").write_text(report.to_json(), encoding="utf-8")

    researcher = report.models["researcher"].mean_reward
    guesser = report.models["guesser"].mean_reward
    assert researcher is not None and guesser is not None and researcher > guesser
    print(f"researcher mean reward {researcher:.1f} > guesser {guesser:.1f}")


if __name__ == "__main__":
    main()
