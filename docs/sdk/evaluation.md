---
route: /docs/sdk/evaluation
title: Python SDK guide
order: 111
description: Build, run, inspect, and export evaluations from Python, using the same projects and results as the plural command-line tool.
audience: developers
nav: true
nav_group: Interfaces
---
# Python SDK guide

The Python SDK lets you set up and run Plural evaluations from your own code. It is
for people who write Python: to script a batch of runs, fit Plural into a notebook or
a pipeline, or build resources that are easier to write as code than as files.

You can use it two ways. Build the pieces directly in Python, or load the ones already
saved in a [project](../getting-started.md#create-a-project) and run them the way
`plural run` does. Either way you end up with a **Job**: one run that sends one or
more Agents at a Task or Benchmark and records every attempt. If the words are new,
read [Core concepts](../getting-started/concepts.md) first.

## Build a Job

Here is a complete evaluation in Python: a grader, one assignment, an exam holding
it, a contestant, and the Job that runs them.

- The **Verifier** is the grader. Here, `resolved` gives a score of 1 when the ticket
  ends up done, and 0 otherwise.
- The **Task** is one assignment: resolve this ticket, in this world, graded this way.
- The **Benchmark** is the exam, a fixed set of Tasks.
- The **Agent** is the contestant: a model plus its instructions.

The example assumes you have created the support queue `environment` from the
[tutorial](../tutorials/support-queue.md). Save this code in a Python file so Plural
can load the Verifier function. A live run needs an API key: store a Plural API key
with `plural auth login --api-key-stdin`, or export `PLURAL_API_KEY`.

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

A few defaults to know:

- Environment, Agent, Harness, Verifier, and Task versions default to `0.1.0`. A
  Benchmark `version` is required.
- A Job defaults to eval mode, one attempt, and concurrency one.
- `client=Client()` authenticates the Job's model calls with your Plural API key. The
  Job still runs on this machine.

## Load project resources

In a [project](../getting-started.md#create-a-project), you can load resources by kind
and name instead of building them:

```python
from plural import Job
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
task = workspace.get("task", "ticket-1")
agent = workspace.get("agent", "careful")
result = Job(task, agents=[agent]).run()
```

`workspace.get` accepts a kind name or its CLI noun, such as `"env"`. It returns the
validated SDK object after loading everything it depends on. An invalid resource
raises `ProjectError` with every problem listed.

This Job runs locally and plans the same Trials as
`plural run --task ticket-1 --agent careful`, but it is not recorded under
`.plural/jobs/`. See [YAML and serialization](../interfaces/yaml.md) for the manifest
format.

### Add a project model

If your project uses a model that is not in the public catalog, such as your own
endpoint, add it with `CatalogContext`:

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

Passing `catalog` to `Workspace` validates the project's Agents and Verifiers against
the same entries.

A Job sends every model call through the Plural gateway at `PLURAL_GATEWAY_URL`,
which must serve the project model. It does not call the Anthropic, Google, Bedrock,
or Azure APIs directly, even though `Client` has adapters for them; see
[Providers and integrations](../reference/integrations.md).

## Plan and run

Before running, you can look at the plan: the Job's id and how many Trials (single
attempts) it will make. Then run it and read each Trial's result.

```python
print(job.plan.job_id, job.plan.trial_count)
result = job.run()
for trial in result.trials:
    print(trial.status, trial.score, trial.receipt.artifact_hashes)
```

Each Trial has a status, a score from its Verifiers, and a receipt that records the
exact inputs it used and the hash of every file it produced.

For power users:

- In async code, use `await job.run_async()`.
- `job.run(resume=True)` continues an interrupted run of the same Job, and refuses when
  any planned input has changed.
- Customize execution with `attempts`, `concurrency`, `per_runtime_concurrency`,
  `RetryPolicy`, provider mappings, `JobStore`, progress callbacks, project policy,
  and catalog.

## Inspect and review

`JobStore` reads the records of past local Jobs:

```python
from plural import JobStore

store = JobStore()
for row in store.list_jobs():
    print(row)
for event in store.events(job.plan.job_id):
    print(event.sequence, event.status)
```

`JobStore()` reads `.plural/jobs` relative to the current directory. From the project
root, that is where `plural run` records local Jobs.

Human review happens in the CLI. If a Task uses a human grader, its Trials wait for a
person's score: list them with `plural review list`, and record a score with
`plural review submit`, passing one `--score criterion=value` per criterion.
`plural review list` does not expose the full contracted evidence view; see
[Reviews](../running/reviews.md).

## Save a new revision

SDK values are frozen: once built, an object never changes. To change one, edit the
source, construct a new object with a new version, validate it, and update the
resources that depend on it.

To save project resources to your hosted project, use
`plural <kind> push <name> --with-deps`. It pushes dependencies first and records each
revision in `plural.lock`. A saved revision is private, available in its project
immediately, and never changes afterwards.

`Client.push` saves one object from Python as an immutable, private revision. An
object that references others needs their hosted revision ids, such as a Task's
`environment_revision_id` and `verifier_revision_ids`. See
[Updating and versioning](../project/updating.md).

Every exported class and function, with its fields and signature, is listed in the
[API reference](../reference/api.md).
