---
route: /docs/getting-started/concepts
title: Core concepts
order: 10
description: "The eight objects you use to evaluate agents: Environment, Runtime, Task, Verifier, Agent, Benchmark, Trial, and Job."
audience: all
nav: true
nav_group: Start
---
# Core concepts

You author a world, a score, and the models you want to compare. Plural runs
that graph and keeps the record.

```mermaid
flowchart LR
  runtime[Runtime]
  env[Environment]
  ver[Verifier]
  task[Task]
  bench[Benchmark]
  agent[Agent]
  job[Job]
  trial[Trial]
  runtime --> env
  env --> task
  ver --> task
  task --> bench
  bench --> job
  agent --> job
  job --> trial
```

## Environment

The Environment is the world the Agent is allowed to take action in. It has
three spaces:

- **Action space** — the actions the Agent may call.
- **State space** — the internal variables that represent the world. The Agent
  never sees State.
- **Observation space** — what the Agent is allowed to see, usually returned by
  `reset` and by each action. You choose which facts appear here. Observation
  is not the whole State.

These docs use the game Wordle as a running example, and a support-ticket
queue when we need a second world. One Environment can host many Tasks: Wordle
is the game; each secret word is a Task. The support queue is the desk; each
ticket is a Task.

Every Environment has a required **Runtime**: the machine image, network
settings, and compute placement. The Environment can also declare secret
*names*. Values are supplied at execution time; they are not stored on the
Runtime object.

See [Environments](../project/environments.md).

## Runtime

Runtime says where that world executes. Changing it changes the Environment
hash.

- `Runtime.docker()` — container, public network, `python:3.12-slim`
- `Runtime.local()` — trusted subprocess on your machine
- `Runtime.daytona()` — remote workspace (`plural[daytona]`)

Local is easy to inspect. It is not a sandbox. Docker is the default when you
want isolation.

See [Runtime](../project/environments.md#runtime).

## Verifier

A Verifier scores a completed Trial: one Agent run in an Environment. It
reads the Agent's trajectory and the State and Observation updates from that
episode. It does not score the Environment itself.

Three kinds:

- **DeterministicVerifier** — a function over an `Episode` (observation,
  state, trajectory, artifacts, usage). Use this when the score is exact.
- **AgentVerifier** — a catalog model that judges the episode against
  criteria.
- **HumanVerifier** — a rubric for a person to score after the Trial.

See [Verifiers](../project/verifiers.md).

## Task

A Task is one unit of work in an Environment. It has instructions, optional
goals, one Environment, and one or more Verifiers. The Environment must be
runnable and each Verifier must be able to score an Episode.

You can set Environment State from the Task (`initial_state`) and attach
temporary data (`info`, Task resources). Reusable world behavior stays on the
Environment; case-specific facts belong on the Task.

See [Tasks](../project/tasks.md).

## Agent

An Agent is instructions, a catalog model, and an optional Harness. Omit the
Harness to use Plural's native loop. It is not bound to an Environment. The
same Agent can play Wordle in one Job and triage tickets in another, including
after you train a replacement model and point the Agent at it.

The Agent takes actions in an Environment to work toward a goal — reasoning
under uncertainty. Model authentication lives on the Job (`client=` or
`api_key=`), not on the Agent.

See [Agents](../project/agents.md).

## Benchmark

A Benchmark is an immutable, versioned, ordered collection of Tasks. Agents
run against that pin so later comparisons stay the same experiment.

A Benchmark run scores each Agent using the Task Verifiers, and records
latency, cost, and how stable those scores are across attempts. Change a
Task, Environment, or Verifier and mint a new Benchmark version.

See [Benchmarks](../project/benchmarks.md).

## Trial

A Trial is one Agent × one Task × one planned attempt. A Job expands into
Trials. A timeout can retry as another *execution* of the same Trial; the
Trial identity does not change.

Each execution records a trajectory, artifacts, logs, and a receipt. Final
Verifiers write the score. A human Verifier pauses the Trial at
`awaiting_review`.

See [Trials](../running/trials.md).

## Job

A Job is how you run a Task or a Benchmark. It holds the Agents, the number
of attempts, concurrency, and whether the run is **eval** or **train**.

Eval is the default: score the Agent and keep the episode record. Train uses
the same graph and adds training-grade capture (exact tokens in and out, plus
Environment rewarders when you declare them). Use train when you want data
for a downstream trainer. Neither mode updates model weights inside Plural.

A live Job needs `Job(..., client=Client())` or `api_key=`. Dry-run does not.

See [Jobs](../running/jobs.md).

When you are ready to install and authenticate, open
[Getting started](../getting-started.md).
