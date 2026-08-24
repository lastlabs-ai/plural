"""Play Wordle by stepping the environment. The LLM is only the policy.

Primary loop (Gymnasium / OpenEnv):

    obs, info = env.reset(task)
    while True:
        response = client.chat(...)   # policy — not part of the env
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            break
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _shared import ensure_out_dir
from enroute import Dataset, Enroute, Environment, TaskData
from enroute.environments import Rollout, is_stopped
from enroute.providers import OpenAICompatible
from enroute.tracing import JSONLSink, Trace
from enroute.types import (
    ChatRequest,
    ChatResponse,
    Choice,
    FunctionCall,
    Message,
    ToolCall,
    Usage,
)
from examples.environment.wordle.env import make_env
from examples.environment.wordle.words import is_allowed

LOCAL_HOSTS = {
    "mlx": "http://127.0.0.1:8080/v1",
    "ollama": "http://127.0.0.1:11434/v1",
    "lmstudio": "http://127.0.0.1:1234/v1",
    "vllm": "http://127.0.0.1:8000/v1",
    "llamacpp": "http://127.0.0.1:8080/v1",
}

_MARK_EMOJI = {"G": "🟩", "Y": "🟨", ".": "⬛"}


class ScriptedWordleProvider:
    """Deterministic offline policy: a list of guess words."""

    name = "openai"

    def __init__(self, guesses: list[str]) -> None:
        self.guesses = guesses
        self.calls = 0

    def chat(self, request: ChatRequest) -> ChatResponse:
        word = self.guesses[min(self.calls, len(self.guesses) - 1)]
        self.calls += 1
        return ChatResponse(
            id=f"wd-{self.calls}",
            model=request.model,
            choices=[
                Choice(
                    message=Message(
                        role="assistant",
                        tool_calls=[
                            ToolCall(
                                id=f"g{self.calls}",
                                function=FunctionCall(
                                    name="guess",
                                    arguments=json.dumps({"word": word}),
                                ),
                            )
                        ],
                    )
                )
            ],
            usage=Usage.from_counts(16, 8, cost=0.0),
            provider=self.name,
            latency_ms=1.0,
        )

    def close(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


def play(
    env: Environment,
    task: TaskData,
    client: Enroute,
    *,
    model: str,
) -> Rollout:
    """One episode: reset, policy, step until the env says stop."""
    obs, _info = env.reset(task, model=model)
    trace_context = env.trace_context()
    while True:
        request = ChatRequest(
            model=model,
            messages=env.messages(),
            tools=env.tool_defs or None,
        )
        response = client.chat(
            model=model,
            messages=request.messages,
            tools=request.tools,
            tags={"environment": env.name, "task_id": task.task_id},
            write_trace=False,
            trace_context=trace_context,
        )
        action = response.message.tool_calls
        obs, _reward, terminated, truncated, info = env.step(
            action,
            request=request,
            response=response,
        )
        if terminated or truncated or is_stopped(info.get("stop_reason")):
            break
    return env.close_episode(client=client)


def _print_episode(title: str, trace: Trace, board: str) -> None:
    print(f"\n== {title} ==")
    reward = trace.outcome.reward if trace.outcome else None
    print(f"reward={reward}  terminated={trace.terminated}")
    print(board)
    for i, decision in enumerate(trace.decisions()):
        action = ", ".join(f"{a.name}({a.arguments})" for a in decision.parsed_action)
        step_r = sum(e.value for e in decision.reward_events)
        print(f"  t={i}  {action}  step_reward={step_r:.2f}")
    print(f"  r_t  (outcome) {trace.decision_rewards(source='outcome')}")
    print(f"  r_t  (both)    {trace.decision_rewards(source='both')}")
    print(f"  G_t  γ=1 both  {trace.returns(gamma=1.0, source='both')}")


def _emoji_row(guess: str, marks: str) -> str:
    tiles = "".join(_MARK_EMOJI.get(mark, mark) for mark in marks)
    return f"{guess}  {tiles}"


def _message_text(message: Message) -> str:
    if message.tool_calls:
        calls = []
        for call in message.tool_calls:
            calls.append(f"{call.function.name}({call.function.arguments})")
        return "tool_calls: " + ", ".join(calls)
    return message.content or ""


def _print_harness(env: Environment, rollout: Rollout) -> None:
    """Show the conversation the policy saw and each recorded decision."""
    print("\n== harness (what the policy was sent) ==")
    print(f"environment={env.name}@{env.version}  max_turns={env.max_turns}")
    print(f"tools={[t.function.name for t in env.tool_defs]}")
    print("secret is hidden from the policy (only in state / final_state)")
    for i, message in enumerate(rollout.messages):
        text = _message_text(message)
        preview = text if len(text) <= 800 else text[:800] + "…"
        print(f"\n[{i}] {message.role}")
        print(preview)

    print("\n== decisions (trace) ==")
    for i, decision in enumerate(rollout.trace.decisions()):
        action = ", ".join(f"{a.name}({a.arguments})" for a in decision.parsed_action)
        step_r = sum(e.value for e in decision.reward_events)
        print(f"\n--- t={i}  {action}  step_reward={step_r:.2f} ---")
        obs = decision.observation
        if isinstance(obs, dict) and obs.get("board"):
            print(obs["board"])
        output = decision.model_output
        if output is not None:
            raw = output.message.content if output.message.content else ""
            if raw:
                print(f"model text: {raw}")
        for tool in decision.tool_calls:
            print(f"tool {tool.name} -> {json.dumps(tool.result, default=str)}")


def _episode_summary(env: Environment, trace: Trace) -> dict[str, object]:
    rows = env.rows
    invalids = [
        tool
        for decision in trace.decisions()
        for tool in decision.tool_calls
        if isinstance(tool.result, dict) and tool.result.get("error")
    ]
    words: list[str] = []
    for decision in trace.decisions():
        for action in decision.parsed_action:
            if action.name == "guess":
                words.append(str(action.arguments.get("word", "")))
    return {
        "name": env.name,
        "won": env.solved,
        "n_guesses": len(rows),
        "invalid_count": len(invalids),
        "words": words,
        "board": [_emoji_row(row.guess, row.pattern) for row in rows],
        "total_reward": (trace.outcome.reward if trace.outcome else None) or 0.0,
        "notes": [
            "observation is a G/Y/. board plus a letter keyboard",
            "the policy sees system + that board after every step (not only tool JSON)",
            "terminal score is (7 - guesses) / 6 if solved, else 0",
            "step rewards: +0.1/new green, +0.03/new yellow, -0.05 invalid",
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Play Wordle via env.reset / env.step. The LLM is only the policy."
    )
    parser.add_argument(
        "--secret",
        default="crane",
        help="Hidden 5-letter answer (must be in the Wordle word list). Default: crane.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Policy model id. With --host / --base-url this is the name your local "
            "server exposes (e.g. mlx-community/Qwen2.5-7B-Instruct-4bit). Without "
            "a local host it is an enroute model id (e.g. openai/gpt-4o-mini). "
            "Omit to run the offline scripted demo."
        ),
    )
    parser.add_argument(
        "--host",
        choices=sorted(LOCAL_HOSTS),
        default=None,
        help=(
            "Local OpenAI-compatible server. mlx = mlx_lm.server on :8080. "
            "Overrides the default --base-url unless you pass --base-url too."
        ),
    )
    parser.add_argument(
        "--mlx",
        action="store_true",
        help="Shortcut for --host mlx (Apple MLX via mlx_lm.server).",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "OpenAI-compatible base URL. Defaults from --host / --mlx "
            f"(mlx {LOCAL_HOSTS['mlx']}, ollama {LOCAL_HOSTS['ollama']}, "
            f"lmstudio {LOCAL_HOSTS['lmstudio']}, vLLM {LOCAL_HOSTS['vllm']})."
        ),
    )
    parser.add_argument(
        "--api-key",
        default="EMPTY",
        help="API key for --base-url. Local servers usually accept EMPTY. Default: EMPTY.",
    )
    return parser.parse_args()


def _resolve_local(args: argparse.Namespace) -> str | None:
    host = "mlx" if args.mlx else args.host
    if args.base_url:
        return args.base_url
    if host:
        return LOCAL_HOSTS[host]
    return None


def _task(secret: str) -> TaskData:
    return TaskData(
        task_id=secret,
        input="Play Wordle. Use guess.",
        expected=secret,
        metadata={"seed": 0},
    )


def _local_client(model: str, base_url: str, api_key: str, sink: Path) -> tuple[Enroute, str]:
    provider = "local"
    server_model = model
    if "/" in model:
        provider, server_model = model.split("/", 1)
    client = Enroute(
        providers={
            provider: OpenAICompatible(
                api_key=api_key,
                base_url=base_url,
                name=provider,
            )
        },
        sink=JSONLSink(sink),
        capture_content=True,
    )
    return client, f"{provider}/{server_model}"


def _run_scripted(env: Environment, task: TaskData, secret: str, out: Path) -> list[Trace]:
    traces = []
    policies = (
        ("solver", ScriptedWordleProvider(["slate", secret])),
        ("misses", ScriptedWordleProvider(["audio", "wordy", "aback", "abase", "abate", "abbey"])),
    )
    for name, provider in policies:
        client = Enroute(
            providers={"openai": provider},
            sink=JSONLSink(out / f"wordle-{name}.jsonl"),
            capture_content=True,
        )
        rollout = play(env, task, client, model="openai/gpt-4o-mini")
        traces.append(rollout.trace)
        board = str(rollout.env.observation) if rollout.env is not None else ""
        _print_episode(name, rollout.trace, board)
        client.close()
    return traces


def main() -> None:
    args = _parse_args()
    secret = str(args.secret).strip().lower()
    if len(secret) != 5 or not is_allowed(secret):
        raise SystemExit(f"--secret must be a valid 5-letter Wordle word, got {secret!r}")
    base_url = _resolve_local(args)
    if (base_url or args.mlx or args.host) and not args.model:
        raise SystemExit(
            "--model is required with --mlx / --host / --base-url "
            "(the name your local server exposes)"
        )

    out = ensure_out_dir()
    env = make_env()
    task = _task(secret)

    if args.model is None:
        traces = _run_scripted(env, task, secret, out)
    elif base_url:
        client, model = _local_client(
            args.model, base_url, args.api_key, out / "wordle-local.jsonl"
        )
        try:
            rollout = play(env, task, client, model=model)
        finally:
            client.close()
        traces = [rollout.trace]
        _report_model_run(model, env, rollout, out)
    else:
        client = Enroute(sink=JSONLSink(out / "wordle-model.jsonl"), capture_content=True)
        try:
            rollout = play(env, task, client, model=args.model)
        finally:
            client.close()
        traces = [rollout.trace]
        _report_model_run(args.model, env, rollout, out)

    ds = Dataset.from_traces("wordle", traces, version=env.version)
    ds.save(out / "wordle-dataset.jsonl")
    print(f"\ndataset={ds.content_hash[:12]}…")


def _report_model_run(title: str, env: Environment, rollout: Rollout, out: Path) -> None:
    board = str(rollout.env.observation) if rollout.env is not None else ""
    _print_episode(title, rollout.trace, board)
    _print_harness(env, rollout)
    summary = _episode_summary(env, rollout.trace)
    (out / "wordle-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out / "wordle-trace.json").write_text(
        rollout.trace.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    print("\n== summary ==")
    print(json.dumps(summary, indent=2))
    print(f"wrote {out / 'wordle-summary.json'} and {out / 'wordle-trace.json'}")


if __name__ == "__main__":
    main()
