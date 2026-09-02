# Create and update hosted objects

Environments, agents, and benchmarks are addressed by a **slug** that is unique
inside the project. You do not need the hosted UUID to read, create, or update
them. Traces stay id-based because there are many of them.

```python
from plural import Client, Environment

client = Client()  # project key, or Client(project="...") for an account key
env = Environment(name="refund-support", version="0.1.0", system_prompt="Be brief.")
client.create(env)   # 409 if refund-support already exists
client.update(env)   # finds it by env.slug
```

`env.create(client)` and `env.update(client)` are aliases.
`client.push(env)` / `env.push(client)` still upsert by slug.

## Identity

| Object | Lookup | Create if the slug exists |
| --- | --- | --- |
| Environment | slug (or id) | `409` |
| Agent | slug (or id) | `409` |
| Benchmark | slug (or id) | `409` |
| Trace | row id or `trace_id` | upserts that `trace_id` |

The slug is derived from the name (`Refund Support` → `refund-support`). Pass
that string to `get`, `update`, `delete`, and to attach an environment or agent
on another object.

```python
client.environments.get("refund-support")
client.agents.get("support").invoke("Refund this ticket")
client.benchmarks.update("smoke", notes="nightly")
```

## Account keys need a project

A **project key** already knows the project. An **account key** must pass it:

```python
client = Client(api_key="plural_...", project="<project_id>")
# or export PLURAL_PROJECT
```

Without a project, studio calls return an error.

## Environment

```python
from plural import Environment

env = Environment(name="refund-support", version="0.1.0")
client.create(env)
client.update(env)
print(env.slug, env.remote_id)
```

`create` fails if the slug is taken. `update` uploads a new revision when the
fingerprint changed.

## Agent

Agents are created on the host with a model and environment slug:

```python
agent = client.agents.create(
    name="support",
    model="openai/gpt-5.6-luna",
    environment_id="refund-support",
)
agent.invoke("Refund this ticket")
```

## Trace

```python
rollout = env.rollout(task, client, model="openai/gpt-5.6-luna")
client.create(rollout.trace, environment_id=env.slug)
```

Traces are stored by `trace_id`. Optional kwargs: `environment_id` (slug or
id), `environment_revision_id`, `agent_id` (slug or id), `run_group_id`.

## Benchmark

```python
from plural import Benchmark, TaskDataset

benchmark = Benchmark(
    env,
    models=["openai/gpt-5.6-luna", "google/gemini-3.7-flash"],
    client=client,
)
report = benchmark.run(dataset=TaskDataset.load("data/refund-support.jsonl"))
client.create(benchmark)          # slug from env.name unless you pass name=
client.update(benchmark)          # replace that slug's report
```

`create` / `update` fail until `run()` has produced `benchmark.report`.
Optional kwargs: `name`, `notes`, `environment_id`, `agent_id`.
