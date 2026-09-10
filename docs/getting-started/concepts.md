# Understand the pieces

Plural evaluates agents in environments they cannot rewrite. The eight
canonical objects are Environment, Harness, Model, Agent (template or
instance), Task, Benchmark, Trial, and Trace.

## The vocabulary

An **environment** is the primary object. It owns instructions, **native
actions**, observation and state schemas, guardrails, resources, and the
**runtime** (container, network policy, compute, and which targets may run
it). Native actions act in the environment and return observations.

A **harness** is a prebuilt agent loop that can be **stamped** onto an
environment. The environment subtracts capabilities the harness may not
use. A stamped harness never receives native actions. Four reference
harnesses (`hermes`, `claude-code`, `codex`, `cursor`) ship as `declared`
manifests only. The only runnable executor in this release is the native
path.

A **model** is the LLM. An **agent** is Model + Environment, optionally plus
a stamped Harness. That configuration is an **agent template**. A live
**agent instance** is a template that has accumulated hosted memory, skills,
data, and experience.

A **task** is one unit of work on an environment. A **benchmark** is an
ordered grouping of those tasks. A **job** expands into **trials**. A
**trial** (also called an episode) is one agent run on one task and
produces a **trace**.

## The four invariants

1. The environment owns native actions.
2. A stamped harness cannot take a native action, and the environment
   restricts what it can do.
3. Templates are configuration; instances hold experience.
4. Unsatisfiable execution requirements fail before any sandbox is created.
   Effective permissions are the intersection of provider capability,
   project policy, environment constraints, harness requirements, and the
   agent request.

See [execution capabilities](../concepts/execution-capabilities.md) and
[harness stamping](../concepts/harness-stamping.md).

## Choose one starting path

### Python environment evaluations

Write `@action` methods on `Environment`, supply `TaskData`, and call
`env.rollout(...)`. `Benchmark` repeats that work across models. Follow the
[Python walkthrough](../tutorials/sdk-walkthrough.md).

### Package execution

Configure `EnvironmentManifest`, an optional `HarnessPackage`,
`AgentTemplate`, and `BenchmarkDefinition`. A `JobSpec` combines them.
A trial is one agent attempting one task once. Start with the
[CLI walkthrough](../tutorials/cli-walkthrough.md).

Native path (`AgentTemplate.harness is None`) exposes environment actions to
the model via `native.actions.v1` or `native.chat.v1`. Stamped declared
harnesses are refused at preflight.

### Hosted objects in Plural Intel

Use `client.environments`, `client.agents.templates`,
`client.agents.instances`, and `client.benchmarks`. A fetched template is
configuration. An instance has memory, skills, data, and experience
counters written through the API.

## What can the agent do?

Read the environment's native actions and instructions. If a harness is
stamped, read the grant matrix (`plural env harness capabilities`) — not
the harness's declared set. `network=none` removes web search, browser,
network fetch, and MCP from every stamp.

`plural env capabilities` and `plural runtime doctor --env` must agree
with what the engine will enforce. The local target is excluded when the
environment requires network isolation, persistence, compose, or resource
limits.

## Local versus hosted changes

Saving a dataset or running a local job does not publish it. Publishing
happens through explicit SDK or CLI push. Changing a local package does
not update already-pinned templates and benchmarks.
