---
route: /docs/project/agents
title: "Agents"
order: 65
description: Choose an available model, add instructions and a Harness, and run your Agent on a Task.
audience: all
nav: true
nav_group: Build
outcome: You can find a model, create an Agent, and evaluate it on your Tasks.
---
# Agents

An Agent combines a model, instructions, and a [Harness](harnesses.md). The model makes decisions; the Harness manages its conversation, tools, and interaction with the Environment.

Create an Agent for each configuration you want to compare. You can change the model, instructions, or Harness while keeping the Tasks and scoring the same.

## Find a model

List the model IDs you may run:

```bash
plural models list
```

Signed out, this shows the catalog bundled with Plural. After `plural auth login`, the hosted service returns only the models your organization permits. Organization admins can restrict models, and the service enforces that list for runs, reruns, and model calls through the gateway, so a model missing from this list will be refused.

From Python, a `Client` exposes the same catalog. `Client()` needs a Plural API key, stored with `plural auth login --api-key-stdin` or set as `PLURAL_API_KEY`:

```python
from plural import Client

client = Client()
for model in client.catalog.models():
    print(model.id)
```

Calling a model requires credentials and an endpoint that supports it. See [Getting started](../getting-started.md) for authentication.

## Create your Agent

Choose an ID from the catalog and give the Agent instructions:

```python
from plural import Agent

agent = Agent(
    name="support-assistant",
    model="openai/gpt-5.6-luna",
    instructions=(
        "Inspect the ticket and follow its support policy. "
        "Use the available actions to categorize it, draft a reply, and resolve it. "
        "Stop when the Environment reports that the ticket is done."
    ),
)
```

This Agent has no Harness, so it uses `native`, Plural's built-in tool loop. You do not need to configure a custom Harness to get started.

Task instructions describe the particular job to do. Agent instructions describe how the agent should approach its work across Tasks. Keep them clear, avoid conflicting rules, and state when to stop.

### Save the Agent in a project

In a project, an Agent is a directory under `agents/` named after it, holding one `agent.yaml`:

```bash
plural agent init support-assistant --model openai/gpt-5.6-luna
```

`agent.yaml` takes the same fields as `Agent`:

```yaml
name: support-assistant
version: 0.1.0
model: openai/gpt-5.6-luna
instructions: >-
  Inspect the ticket and follow its support policy. Use the available actions
  to categorize it, draft a reply, and resolve it. Stop when the Environment
  reports that the ticket is done.
```

`name` must match the directory name. `harness` is optional: it names a Harness in the project's `harnesses/` directory or a built-in (`hermes`, `claude-code`, or `codex`), and `harness_kwargs` sets a built-in's options. `auth_mode: none` marks an Agent whose Harness never calls a model, so it runs without credentials. Model keys and other credentials are never written in `agent.yaml`.

`plural agent validate support-assistant` checks the model id, the Harness, and its options. `plural agent push support-assistant --with-deps` saves a private revision, together with a project Harness that is not hosted yet.

## Use a different Harness

Attach a built-in by name, or pass an instance of a custom `Harness` subclass
from the [Harnesses guide](harnesses.md#build-a-custom-harness):

```python
claude = Agent(
    name="support-claude",
    model="anthropic/claude-sonnet-5",
    instructions="Follow the support policy and finish the ticket using the available tools.",
    harness="claude-code",
    harness_kwargs={"reasoning_effort": "high"},
)

custom = Agent(
    name="support-custom-loop",
    model="openai/gpt-5.6-luna",
    instructions="Follow the support policy and finish the ticket using the available tools.",
    harness=harness,
)
```

The Harness runs in the Runtime selected by the Task's Environment. Built-ins install their CLI there. A custom Harness still needs its dependencies in that Runtime.

Model authentication is supplied through the Job's Client. A custom Harness declares the environment names it reads, and `secret_names` grants a subset of those names. If one of those names is missing when the run starts, the error lists it and does not include the value. See [Harnesses](harnesses.md).

## Evaluate the Agent

From the CLI, run a saved Agent on a Task, or try a model without saving an Agent first:

```bash
plural run --task ticket-1 --agent support-assistant
plural run --task ticket-1 --model openai/gpt-5.6-luna
```

Every run is a new Job. A local run is recorded under `.plural/jobs/`; a run with `--hosted` is recorded in the hosted project. Add `--dry-run` to see the plan without calling a model. A live local run needs an API key, a Plural key or your own `OPENAI_API_KEY`; a browser login alone is not accepted for model calls.

In Python, given a Task named `task`, run the Agent with your Client:

```python
from plural import Job

job = Job(task, agents=[agent], client=client)
print(job.plan.trial_count)
result = job.run()
```

Use a [Benchmark](benchmarks.md) to evaluate multiple Tasks and compare Agents.

## Make a useful comparison

Start by changing one thing at a time:

- **Model:** keep the Harness and instructions the same.
- **Instructions:** keep the model and Harness the same.
- **Harness:** keep the model and Task set the same.

Use repeated attempts to see how consistent the results are. Inspect actions and scoring evidence as well as the final score.

Leave `fallback_models` unset when comparing individual models, so a different model does not silently complete the work. Advanced endpoint setup and application routing are covered in [Providers and integrations](../reference/integrations.md).
