# Wordle environment

The environment *is* the game: secret, board, `guess`, observations, and rewards. You play it with `reset` / `step`. The model is only the policy that picks a word.

## Run

From the repo root:

```bash
uv run python examples/environment/wordle/run.py --secret crane
```

`--secret` is the hidden 5-letter answer. It must be in the Wordle word list (`data/allowed.txt` / `data/answers.txt`). If you omit it, the secret is `crane`.

```bash
uv run python examples/environment/wordle/run.py
uv run python examples/environment/wordle/run.py --secret slate
```

Without `--model`, the script runs two offline policies (no API key):

- **solver** — guesses `slate`, then the secret
- **misses** — six valid words that are not the secret

Each episode prints the board, per-step rewards, and discounted returns. The offline default deliberately runs two episodes and saves their two traces as a small dataset.

`WordleEnv` allows six **valid** guesses. An invalid tool call does not consume a
guess slot, but every `env.step(...)` still consumes one episode turn. The
larger `max_turns` value is only a safety budget for malformed or repeated
invalid calls.

## Local model (laptop)

`--host` picks a default OpenAI-compatible `/v1` URL. `--model` is the name your server exposes. The model is the policy; it must support tool calls (`guess`).

### MLX (Apple Silicon)

Install [`mlx-lm`](https://github.com/ml-explore/mlx-lm) and start its server. Port `8080` is the default.

```bash
pip install mlx-lm
mlx_lm.server --model mlx-community/Qwen2.5-7B-Instruct-4bit --port 8080
```

Then:

```bash
uv run python examples/environment/wordle/run.py --secret crane \
  --mlx --model mlx-community/Qwen2.5-7B-Instruct-4bit
```

`--mlx` is the same as `--host mlx` (`http://127.0.0.1:8080/v1`). Pick a model that actually emits tool calls; many 1–3B checkpoints will guess invalid words or ignore the board.

### Other local hosts

```bash
# Ollama
uv run python examples/environment/wordle/run.py --secret crane --host ollama --model llama3.2

# LM Studio
uv run python examples/environment/wordle/run.py --secret crane --host lmstudio --model local-model

# vLLM
uv run python examples/environment/wordle/run.py --secret crane \
  --host vllm --model meta-llama/Llama-3.1-8B-Instruct
```

Or pass `--base-url` yourself. `--api-key` defaults to `EMPTY`.

A live model run executes one episode and persists one episode trace: per-turn client calls use `write_trace=False`, then `close_episode(client=client)` writes the completed trace. It prints the **harness** (every message the policy was sent) and each **decision** (observation, tool result, step reward), then writes `.plural/examples/wordle-summary.json` and `wordle-trace.json`.

## Hosted model

If the model is already configured on your Plural client (env keys, etc.):

```bash
uv run python examples/environment/wordle/run.py --secret crane --model openai/gpt-4o-mini
```

## Play loop

```python
from plural.environments import is_stopped

obs, info = env.reset(task)
while True:
    response = client.chat(
        model=model,
        messages=env.messages(),
        tools=env.tool_defs,
        write_trace=False,
    )
    obs, reward, terminated, truncated, info = env.step(
        response.message.tool_calls, request=..., response=response
    )
    if is_stopped(info["stop_reason"]):
        break
rollout = env.close_episode(client=client)
```

Prefer `env.rollout(...)` or `env.run_episode(...)` for policy-driven runs. In a manual loop, `write_trace=False` avoids a standalone LLM trace for every turn; `close_episode(client=client)` persists the single episode trace. Do not call `observe` to drive the agent: `reset` and `step` already return the observation.

Wordle is a tool-only environment: it defines `guess` and inherits the base
`apply_action` tool dispatcher. Framework-owned final `step()` records the
decision, advances the turn, rebuilds the observation, and checks termination.

To compare policies or model IDs over environment tasks, see the
[benchmarking examples](../../benchmarking/README.md).

## Named benchmarks on one env

A benchmark is a reusable eval, not a single run. The same `WordleEnv` can host several:

- **wordle-easy** — common answers (`crane`, `slate`, `trace`, …), primary metric `scores.solved`
- **wordle-hard** — rarer answers, same solve-rate goal
- **wordle-efficiency** — same tasks, primary metric `scores.efficiency` (fewest guesses)

```python
from plural import Benchmark, TaskData, TaskDataset

easy = TaskDataset(
    name="wordle-easy",
    version="1.0.0",
    tasks=[
        TaskData(task_id=word, input="Play Wordle. Use guess.", expected=word)
        for word in ("crane", "slate", "trace", "stare", "raise")
    ],
)
report = Benchmark(
    WordleEnv(),
    models=["openai/gpt-5.6-luna", "anthropic/claude-haiku-4-5"],
    client=client,
    name="wordle-easy",
    description="Common Wordle answers.",
    primary_metric="scores.solved",
    environment_factory=WordleEnv,
).run(dataset=easy)
client.create(report)
```

Ten words on one model is ten episode traces in one `run_group_id`. Studio Cases shows each word and the guess sequence.

## Files

| Path | Role |
| --- | --- |
| [`env.py`](env.py) | `WordleEnv`, `WordleObservation`, `WordleState` |
| [`words.py`](words.py) | Load lists, `pattern()`, `is_allowed()` |
| [`data/answers.txt`](data/answers.txt) | Official secrets |
| [`data/allowed.txt`](data/allowed.txt) | Legal guesses |
| [`run.py`](run.py) | CLI + scripted `reset` / `step` loop |
| [`walkthrough.ipynb`](walkthrough.ipynb) | Brief environment, trace, and benchmark tutorial |
