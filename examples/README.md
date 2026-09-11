# Plural examples

## Routing (start here)

See [`routing/README.md`](routing/README.md) for the full walkthrough.

```bash
export PLURAL_API_KEY=plural-...

uv run python examples/routing/quickstart/basic.py
uv run python examples/routing/catalog/list_models.py
uv run python examples/routing/models/openai/basic.py
uv run python examples/routing/models/anthropic/basic.py
uv run python examples/routing/models/google/basic.py
uv run python examples/routing/models/fireworks/basic.py
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
```

| Path | Purpose |
| --- | --- |
| [`routing/quickstart/`](routing/quickstart/) | First call (basic + tracing) |
| [`routing/catalog/`](routing/catalog/) | List model ids |
| [`routing/models/`](routing/models/) | OpenAI, Anthropic, Google, Fireworks |
| [`routing/custom/`](routing/custom/) | Your own OpenAI-compatible server |
| [`routing/byok/`](routing/byok/) | Bring-your-own upstream keys |

## Other folders

| Folder | What it covers |
| --- | --- |
| [`tracing/`](tracing/) | Redaction, sinks, late labels |
| [`environment/`](environment/) | Canonical typed Environment authoring notebooks |
| [`benchmarking/`](benchmarking/) | Cross-Environment `BenchmarkDefinition` Jobs |
| [`jobs/`](jobs/) | Packages, local/Docker/Daytona Jobs, attempts, events, and Studio revisions |

Each Environment notebook covers typed state/observation, actions, runtime
placement, and compiling an immutable `EnvironmentDefinition`.

The two [benchmarking flows](benchmarking/README.md) are also offline:

```bash
uv run python examples/benchmarking/01_compare_models.py
uv run python examples/benchmarking/02_compare_policies.py
```

The [package execution examples](jobs/README.md) are offline by default.
Docker, Daytona, and hosted Studio writes require explicit opt-in environment
variables so CI never calls external services accidentally.
