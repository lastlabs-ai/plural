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

Authenticate once using the [Getting started](../getting-started.md) setup:

```bash
plural auth login
```

Then use the Client's model catalog to see the available model IDs:

```python
from plural import Client

client = Client()
for model in client.catalog.models():
    print(model.id)
```

The catalog lists models known to your Client. Calling a model also requires credentials and an endpoint that supports it. See [Getting started](../getting-started.md) for authentication.

You can browse the same catalog from the command line:

```bash
plural models list
```

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

This Agent uses Plural's built-in Harness. You do not need to configure a custom Harness to get started.

Task instructions describe the particular job to do. Agent instructions describe how the agent should approach its work across Tasks. Keep them clear, avoid conflicting rules, and state when to stop.

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

Given a Task named `task`, run the Agent with your Client:

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

Leave fallback models unset when comparing individual models, so a different model does not silently complete the work. Advanced endpoint setup and application routing are covered in [Providers and integrations](../reference/integrations.md).
