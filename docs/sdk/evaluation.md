---
route: /docs/sdk/evaluation
title: Python SDK guide
order: 111
description: Build, run, inspect, and export evaluations using the Python SDK.
audience: developers
nav: true
nav_group: Interfaces
---
# Python SDK guide

Use the Python SDK to compose an Environment, Tasks, Verifiers, and Agents into a Job. You can run the Job directly or export it to YAML for the CLI.

## Build a Job

The following example assumes you have created the support queue `environment` from the [tutorial](../tutorials/support-queue.md). Save this code in a Python file so Plural can load the Verifier function. Configure authentication with `plural auth login` before a live run.

```python
from plural import Agent, Benchmark, Client, Episode, Job, Task, VerifierOutput
from plural.verifiers import DeterministicVerifier

def resolved(episode: Episode) -> VerifierOutput:
    return VerifierOutput(score=float(bool(episode.observation.get("done"))))

verifier = DeterministicVerifier(name="resolved", check=resolved)
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
)
job = Job(benchmark, agents=(agent,), client=Client())
```

Environment, Agent, Harness, Verifier, and Task versions default to `0.1.0`.
Benchmark `version` is required. Job defaults are eval mode, one attempt, and
concurrency one.

To publish the task to Plural Intel instead of running it locally, see
[Publish a Task object](../project/tasks.md#publish-a-task-object):
`task.push()` publishes the revision, resolving the bound Environment and
Verifier to their current published revisions.

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
    print(trial.status, trial.score, trial.receipt.artifact_hashes)
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

Constructor fields and method signatures follow the objects shown in this guide.
