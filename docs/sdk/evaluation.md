---
route: /docs/sdk/evaluation
title: Python SDK guide
order: 111
description: Build, serialize, plan, run, inspect, version, and review the canonical evaluation graph with the Python SDK.
audience: developers
nav: true
nav_group: Interfaces
---
# Python SDK guide

Python constructors are the semantic source for YAML and CLI.

## Golden flow

```python
from pathlib import Path
from plural import Agent, Benchmark, Job, Task
from plural.verifiers import DeterministicVerifier

verify = Path("verify.py").read_text(encoding="utf-8")
verifier = DeterministicVerifier(
    name="resolved",
    check=("python", "-c", verify),
)
task = Task(
    name="ticket-1",
    instructions="Resolve the support ticket.",
    environment=environment,
    verifiers=(verifier,),
)
benchmark = Benchmark(
    name="support",
    version="1.0.0",
    tasks=(task,),
)
agent = Agent(
    model="openai/gpt-5.6-luna",
    instructions="Use the available actions.",
    secret_names=("OPENAI_API_KEY",),
)
job = Job(benchmark, agents=(agent,))
```

Environment, Agent, Harness, Verifier, and Task versions default to `0.1.0`.
Benchmark `version` is required. Job defaults are eval mode, one attempt, and
concurrency one.

## Serialize and resolve

```python
from plural.project import dump, load

dump(job, "job.yaml")
restored = load("job.yaml")
assert restored.content_hash == job.content_hash
assert restored.plan == job.plan
```

`Resolver` also loads `path.py:object` references and nested relative YAML
references. Use `CatalogContext` when adding project model entries:

```python
from plural import CatalogContext, ModelCatalog, ModelSpec
from plural.catalog import ModelEndpoint

context = CatalogContext(
    ModelCatalog(
        entries=(
            ModelSpec(
                id="project/support-model",
                endpoints=(
                    ModelEndpoint(
                        provider="project-gateway",
                        upstream_id="support-model-v2",
                    ),
                ),
            ),
        )
    )
)
agent = context.agent(model="project/support-model", provider="project-gateway")
restored = context.resolver(".").load("job.yaml")
```

The project endpoint must be reachable through `OPENAI_BASE_URL` or
`PLURAL_GATEWAY_URL` and accept OpenAI-compatible chat completions. `Client`
provider adapters are separate from Job native execution; Job does not call
Anthropic, Google, Bedrock, or Azure native APIs directly.

## Plan and run

```python
print(job.plan.job_id, job.plan.trial_count)
result = job.run()
for trial in result.trials:
    print(trial.status, trial.reward, trial.receipt.artifact_hashes)
```

In async code, use `await job.run_async()`. Pass `resume=True` only for the same
locked Job. Customize execution with `attempts`, `concurrency`,
`per_runtime_concurrency`, `RetryPolicy`, provider mappings, `JobStore`,
progress callbacks, project policy, and catalog.

## Inspect and review

```python
from plural import JobStore

store = JobStore()
for row in store.list_jobs():
    print(row)
for event in store.events(job.plan.job_id):
    print(event.sequence, event.status)
```

The supported local review interface is the CLI and currently accepts one
criterion score. It does not expose full contracted evidence or
multi-criterion submission; see [Reviews](../running/reviews.md).

## Publish a new revision

SDK values are frozen. Edit source, construct a new object with a new semantic
version, validate it, and repin dependents. Hosted `Client.create`,
`Client.update`, and `Client.push` publish canonical revisions through the
service; they do not make an existing published revision mutable.

Use [Fields](../reference/fields.md) for every constructor field and
[API reference](../reference/api.md) for method signatures.
