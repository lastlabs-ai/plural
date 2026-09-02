# Push environments, traces, and benchmarks

`client.push(x)` syncs a local object to the hosted Plural project. Use it for
environments, traces, and benchmark reports. Agents are not pushed: they have
to be created on the host with a model and environment.

```python
from plural import Client, Environment

client = Client()  # project key, or Client(project="...") for an account key
env = Environment(name="refund-support", version="0.1.0", system_prompt="Be brief.")
client.push(env)
```

`env.push(client)` is kept as an alias for `client.push(env)`.

## What you can push

| Object | What happens |
| --- | --- |
| `Environment` | Creates the environment if needed, then uploads a revision |
| `Trace` | Ingests the trace into the project |
| `Benchmark` | Uploads `benchmark.report` after `run()` |
| `Report` | Uploads the report directly |

Agents stay on `client.agents.create(...)` and `client.agents.get(id).invoke(...)`.
They need hosted client context (model, environment binding, invoke URL) and
are not local-first objects.

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
client.push(env)
print(env.remote_id)
```

Optional kwargs: `environment_id` (update an existing remote env), `name`,
`description`. After the first push, later calls upload a new revision for the
same `env.remote_id`.

## Trace

```python
rollout = env.rollout(task, client, model="openai/gpt-5.6-luna")
client.push(rollout.trace, environment_id=env.remote_id)
```

Optional kwargs: `environment_id`, `environment_revision_id`, `agent_id`,
`run_group_id`.

## Benchmark

```python
from plural import Benchmark, TaskDataset

benchmark = Benchmark(
    env,
    models=["openai/gpt-5.6-luna", "google/gemini-3.7-flash"],
    client=client,
)
report = benchmark.run(dataset=TaskDataset.load("data/refund-support.jsonl"))
client.push(benchmark)
# or client.push(report, environment_id=env.remote_id)
```

`client.push(benchmark)` fails until `run()` has produced `benchmark.report`.
Optional kwargs: `name`, `notes`, `environment_id`, `agent_id`.
