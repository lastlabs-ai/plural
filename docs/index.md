# Plural

**One router. One trace. Environments and benchmarks that speak the same language.**

Plural is a Python package for builders putting AI into products. It gives you:

1. **Unified routing** across model providers (OpenAI, Anthropic, Google, and OpenAI-compatible vendors)
2. **First-class traces** — the same record for production traffic and eval rollouts
3. **Environments** — RL-style harnesses (tasks + tools + scorers) that *generate* those traces
4. **Benchmarks** — run an environment across models and get a scored report

```mermaid
flowchart LR
  App[Your app] --> Client[Plural client]
  Env[Environment] --> Client
  Client --> Router[Router]
  Router --> Trace[Trace]
  Trace --> TraceDataset[TraceDataset / Dataset]
  TraceDataset --> Training[Training / export]
  TaskDataset[TaskDataset] --> Bench[Benchmark]
  Env --> Bench
```

## Why a unified Trace?

If production traffic and eval harnesses emit different shapes, every downstream promise breaks. Plural makes them the same object so you can:

- Understand which prompts succeed
- Build datasets from real traffic
- Train or rank models against your environment
- Eventually autoroute each prompt to the best model for *your* data

## Install

```bash
pip install plural
# or
uv add plural
```

## 60-second taste

```bash
export PLURAL_API_KEY=plural-...
```

```python
from plural import Client, Message

client = Client()
response = client.chat(
    model="openai/gpt-4o-mini",
    messages=[Message(role="user", content="Hello")],
)
print(response.text)
client.close()
# Traces land in .plural/traces.jsonl by default
```

Optional bring-your-own-key: `Client(providers={"openai": "sk-..."})`.

Sync a local environment, trace, or benchmark report with `client.push(x)`.
`env.push(client)` is an alias. Agents are created on the host with
`client.agents.create(...)` because they need a model and environment.
See [Push to Plural](guides/push-to-plural.md).

## Next

- [Quickstart](quickstart.md)
- [Routing examples walkthrough](guides/routing-examples.md)
- [What is a Trace?](concepts/trace.md)
- [What is an Environment?](concepts/environment.md)
