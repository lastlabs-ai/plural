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

Use the Python SDK to compose an Environment, Tasks, Verifiers, and Agents into a Job, or to load the resources of a project and run them the way `plural run` does.

## Build a Job

The following example assumes you have created the support queue `environment` from the [tutorial](../tutorials/support-queue.md). Save this code in a Python file so Plural can load the Verifier function. A live run needs an API key: store a Plural API key with `plural auth login --api-key-stdin`, or export `PLURAL_API_KEY`.

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
concurrency one. `client=Client()` authenticates the Job's model calls with your
Plural API key; the Job still runs on this machine.

## Load project resources

In a [project](../getting-started.md#create-a-project), load resources by kind
and name instead of constructing them:

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
task = workspace.get("task", "ticket-1")
agent = workspace.get("agent", "careful")
result = Job(task, agents=[agent]).run()
```

`workspace.get` accepts a kind name or its CLI noun, such as `"env"`, and
returns the validated SDK object after loading everything it depends on. An
invalid resource raises `ProjectError` with every problem listed. The Job runs
locally and plans the same Trials as `plural run --task ticket-1 --agent
careful`, but it is not recorded under `.plural/jobs/`. See
[YAML and serialization](../interfaces/yaml.md) for the manifest format.

Use `CatalogContext` when adding project model entries:

```python
from plural import CatalogContext, ModelCatalog, ModelSpec
from plural.catalog import ModelEndpoint
from plural.project import Project, Workspace

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
workspace = Workspace(Project.find(), catalog=context.catalog)
```

Passing `catalog` to `Workspace` validates the project's Agents and Verifiers
against the same entries.

The project endpoint must be reachable through `OPENAI_BASE_URL` or
`PLURAL_GATEWAY_URL` and accept OpenAI-compatible chat completions. A Job sends
every model call through that OpenAI-compatible endpoint. It does not call the
Anthropic, Google, Bedrock, or Azure APIs directly, even though `Client` has
adapters for them; see [Providers and integrations](../reference/integrations.md).

## Plan and run

```python
print(job.plan.job_id, job.plan.trial_count)
result = job.run()
for trial in result.trials:
    print(trial.status, trial.score, trial.receipt.artifact_hashes)
```

In async code, use `await job.run_async()`. `job.run(resume=True)` continues an
interrupted run of the same Job and refuses when any planned input has changed.
Customize execution with `attempts`, `concurrency`,
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

`JobStore()` reads `.plural/jobs` relative to the current directory. From the
project root, that is where `plural run` records local Jobs. Review local Trials
with the CLI: `plural review list` and
`plural review submit`, with one `--score criterion=value` per criterion.
`plural review list` does not expose the full contracted evidence view; see
[Reviews](../running/reviews.md).

## Save a new revision

SDK values are frozen. Edit the source, construct a new object with a new
version, validate it, and update the resources that depend on it. To save project resources to your
hosted project, use `plural <kind> push <name> --with-deps`, which pushes
dependencies first and records each revision in `plural.lock`. `Client.push`
saves one object as an immutable, private revision; an object that references
others needs their hosted revision ids, such as a Task's
`environment_revision_id` and `verifier_revision_ids`. A saved revision is available in its project
immediately and never changes afterwards. See
[Updating and versioning](../project/updating.md).

Every exported class and function, with its fields and signature, is listed in
the [API reference](../reference/api.md).
