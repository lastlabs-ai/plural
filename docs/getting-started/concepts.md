# Understand the pieces

Imagine evaluating an assistant that looks up customer orders. You need to
provide the order data, decide which actions are available, give it customer
questions, and check its answers. Plural separates those concerns so you can
repeat the same test with a different model.

## The vocabulary you need first

An **environment** defines the setting for the work. In the Python API, it can
hold state and expose Python tools. In package execution, its manifest declares
instructions, tasks, commands, execution requirements, and an optional verifier.

A **task** is one input to that environment, with a stable identifier and,
optionally, an answer or other information reserved for evaluation.

A **model** produces responses and requests actions. A **harness** manages the
model interaction and execution loop. A packaged **agent** binds one model to
one exact environment revision and one exact harness revision.

A **benchmark** defines the comparison. A **result** tells you what happened;
a **trace** records the model calls and actions that led to it. A successful
process exit does not necessarily mean the task was solved: look at its score.

## Choose one starting path

### Python environment evaluations

Use this when you want to write tools as Python functions, experiment in a
notebook, or score model behavior in a simulator.

You author `Environment`, supply `TaskData`, and call `env.rollout(...)`.
`Benchmark` repeats that work across models. The environment drives the episode
loop; `Policy.act()` is the extension for choosing the next action.

You do not need to create a hosted Agent or a package manifest first.
Follow the [Python walkthrough](../tutorials/sdk-walkthrough.md).

### Package execution with the CLI or Python

Use this when you need a separately executable harness, a container or remote
sandbox, durable job state, or isolated verification.

You configure `EnvironmentManifest`, `HarnessPackage`, `AgentSpec`, and
`BenchmarkDefinition`. A `JobSpec` combines them. A **trial** is one agent
attempting one task once. Two agents, five tasks, and three attempts produce
30 trials. Retrying a failed execution keeps the same trial identity.

Start with the [CLI walkthrough](../tutorials/cli-walkthrough.md). The
[Python job API](../sdk/package-jobs.md) uses the same execution domain.

### Hosted objects in Plural Intel

Use `client.environments`, `client.agents`, and `client.benchmarks` to read and
manage project objects. These helpers are also available through `client.studio`;
older documentation and source code call the hosted integration “Studio.”

A fetched environment or benchmark is a dictionary of hosted data. A fetched
agent is a `RemoteAgent` handle with `.invoke()`. Neither is automatically a
local executable package. `from plural import Agent` is an alias for that hosted
handle; use `AgentSpec` for a local packaged agent.

See [fetch and update objects](../guides/push-to-plural.md) for a complete path.

## What can the agent do?

Start by reading the environment's tools or command declarations and its
instructions. Then check the harness and runtime: a harness with shell access
may have access beyond the model's displayed tool list.

In-process Python tools run with your application's permissions. The CLI's
`local` provider runs child processes under your user account. Neither is an
isolation boundary. Docker and Daytona provide different enforceable controls.
Plain-language guardrails are instructions, not filesystem or service permissions.

Keep evaluator-only answers in `expected` / `verifier_input`, and avoid putting
them in public task metadata, instructions, or source files visible to the
harness. The [security guide](../operations/security.md) explains the boundaries.

## Local versus hosted changes

Saving a dataset or running a local job does not publish it to Plural Intel.
A model call still contacts its configured provider. Publishing happens through
explicit SDK create/update/push calls, `plural env push`, `plural run --sync`,
or `plural job upload`.

Changing a local package does not update already-pinned agents and benchmarks.
Those references must be regenerated for the new revision. Changing hosted
metadata does not change the source code installed on your computer.
