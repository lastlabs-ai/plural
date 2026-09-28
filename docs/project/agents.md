---
route: /docs/project/agents
title: "Agents"
order: 65
description: An Agent is a contestant you evaluate, a model plus its instructions. Pick a model, write the instructions, and run it on your Tasks.
audience: all
nav: true
nav_group: Build
outcome: You can find a model, create an Agent, and evaluate it on your Tasks.
---
# Agents

An **Agent** is a contestant: a model from the catalog, plus the instructions you
give it. It is the thing you are evaluating, and it is what ends up on a leaderboard.

Every Agent also has a [Harness](harnesses.md), the way the contestant plays: the
loop that shows the model what it can see, asks it what to do, and carries out the
move. You rarely have to think about it. If you don't pick one, Plural uses its own
built-in loop.

## Why make more than one

The point of an Agent is comparison. Create one Agent for each setup you want to
try, then run them all on the same Tasks with the same grading. For example:

- `careful`: a model told to read the policy before acting.
- `concise`: the same model, told to finish quickly.
- `support-claude`: a different model, playing through Claude Code.

Because the Tasks and scoring stay the same, any difference in the results comes
from the Agent.

Agents are not tied to one world. The same Agent can play Wordle in one run and work
support tickets in the next.

## What an Agent sees

An Agent only ever sees two things: the Task's instructions and the Environment's
Observations (the part of the world it is shown). It never sees the score, the
rewards, the hidden State, or anything the grader knows. That keeps the test fair.

## Find a model

Start by listing the model IDs you may run:

```bash
plural models list
```

What you see depends on who you are:

- **Signed out**, you see the catalog bundled with Plural.
- **Signed in, outside an organization**, you see the whole catalog.
- **Signed in, in an organization**, you see the models your organization offers:
  models it serves from its own cloud endpoints, its private models, and any models
  an admin has explicitly allowed. If the organization has configured none of these,
  you see the whole catalog.

Run `plural models list --all` to see every catalog model. Models your organization
does not permit are marked `not permitted`; the service refuses them for runs,
reruns, and model calls through the gateway.

You can also browse the model Catalog in the web app, with model cards and prices.

From Python, a `Client` exposes the same catalog. `Client()` needs a Plural API key,
stored with `plural auth login --api-key-stdin` or set as `PLURAL_API_KEY`:

```python
from plural import Client

client = Client()
for model in client.catalog.models():
    print(model.id)
```

Calling a model requires credentials and an endpoint that supports it. See
[Getting started](../getting-started.md) for authentication.

## Create your Agent

Choose a model ID from the catalog and write the instructions:

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

This Agent has no Harness, so it uses `native`, Plural's built-in tool loop. You do
not need a custom Harness to get started.

> **Tip:** Task instructions describe *this particular assignment*. Agent
> instructions describe *how to approach work in general*, across every Task. Keep
> them clear, avoid rules that conflict, and say when to stop.

### Save the Agent in a project

In a project, an Agent is a folder under `agents/` named after it, holding one
`agent.yaml` file. Create one with:

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

Check it, then save a private copy to your hosted project:

```bash
plural agent validate support-assistant
plural agent push support-assistant --with-deps
```

`validate` checks the model ID, the Harness, and its options. `push` saves a private
revision, together with any project Harness the Agent uses that is not hosted yet.
Pushing never makes anything public.

The fields, for reference:

- `name` must match the folder name, which is also the hosted slug. An optional
  `title` sets the display name.
- `harness` is optional. It names a Harness in the project's `harnesses/` folder, or a
  built-in (`hermes`, `claude-code`, or `codex`).
- `harness_kwargs` sets a built-in Harness's options.
- `auth_mode: none` marks an Agent whose Harness never calls a model, so it runs
  without credentials.

Model keys and other credentials are never written in `agent.yaml`.

## Use a different Harness

To have the same kind of contestant play a different way, attach a built-in Harness
by name, or pass an instance of a custom `Harness` subclass from the
[Harnesses guide](harnesses.md#build-a-custom-harness):

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

The Harness runs inside the Runtime (the place the world runs, usually a Docker
container) chosen by the Task's Environment. Built-ins install their command-line
tool there. A custom Harness still needs its dependencies in that Runtime.

Model authentication comes from the Job's Client, not from the Agent. A custom
Harness declares the environment variable names it reads, and the Agent's
`secret_names` grants a subset of those names. If one of those names is missing when
the run starts, the error lists it and does not include the value. See
[Harnesses](harnesses.md).

## Evaluate the Agent

From the command line, run a saved Agent on a Task, or try a model without saving an
Agent first:

```bash
plural run --task ticket-1 --agent support-assistant
plural run --task ticket-1 --model openai/gpt-5.6-luna
```

Every run is a new Job, one run you start. Add `--dry-run` to see the plan without
calling a model.

A few things to know:

- A local run is recorded under `.plural/jobs/`. A run with `--hosted` is recorded in
  the hosted project, where you can also see it in the web app under Jobs.
- A live local run sends every model call through the Plural gateway, so it needs a
  Plural API key. A browser login alone is not accepted for model calls.

In Python, given a Task named `task`, run the Agent with your Client:

```python
from plural import Job

job = Job(task, agents=[agent], client=client)
print(job.plan.trial_count)
result = job.run()
```

To compare Agents across many Tasks at once, use a [Benchmark](benchmarks.md).

## Make a useful comparison

Change one thing at a time, so you know what caused a difference:

- **Model:** keep the Harness and instructions the same.
- **Instructions:** keep the model and Harness the same.
- **Harness:** keep the model and Task set the same.

Run repeated attempts to see how consistent the results are. Look at the actions the
Agent took and the grader's evidence, not just the final score.

> **Good to know:** Leave `fallback_models` unset when comparing individual models.
> Otherwise a different model can quietly finish the work and take the credit.

Advanced endpoint setup and routing work to the model you choose are covered in
[Providers and integrations](../reference/integrations.md).
