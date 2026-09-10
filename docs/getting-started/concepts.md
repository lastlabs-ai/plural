---
route: /docs/getting-started/concepts
title: "Understand the pieces"
order: 20
description: "Plural evaluates Agents in Environments they cannot rewrite. The canonical execution graph contains Environment, Harness, AgentDefinition, Task, Verifier, Benchmark, Job, Trial, TrialExecution, ProgressEvent, and Trace."
audience: all
---
# Understand the pieces

Plural evaluates Agents in Environments they cannot rewrite. The canonical
execution graph contains Environment, Harness, AgentDefinition, Task, Verifier,
Benchmark, Job, Trial, TrialExecution, ProgressEvent, and Trace.

## The vocabulary

An **environment** is the primary object. It owns overview, **native actions**,
observation and state schemas, guardrails, resources, and the
**runtime** (container, network policy, compute, and which targets may run
it). Native actions act in the environment and return observations.

A **harness** is a prebuilt agent loop that can be **stamped** onto an
environment. The environment subtracts capabilities the harness may not
use. A stamped harness never receives native actions. Four reference
harnesses (`hermes`, `claude-code`, `codex`, `cursor`) ship as `declared`
manifests only. The only runnable executor in this release is the native
path.

A **model** is the LLM. An **AgentDefinition** owns its model, instructions,
routing, and optional Harness. It is not bound to an Environment.

A **Task** is a revisioned unit of work that pins one Environment revision and
one or more weighted Verifier revisions. A **Verifier** is deterministic,
agent-based, or human, with runtime/connectivity independent of the
Environment. A **Benchmark** is an ordered grouping of Task revisions and may
span Environments.

A **Job** selects either a Task or Benchmark and expands Agents × Tasks ×
attempts into **Trials**. A Trial is one logical attempt. Each retry is a new
**TrialExecution** under that Trial. Durable **ProgressEvents** expose the
state transitions; a human Verifier moves a Trial to `awaiting_review`.

## The four invariants

1. The environment owns native actions.
2. A stamped harness cannot take a native action, and the environment
   restricts what it can do.
3. Agents are Environment-independent; compatibility is stamped per Trial.
4. Unsatisfiable execution requirements fail before any sandbox is created.
   Effective permissions are the intersection of provider capability,
   project policy, environment constraints, harness requirements, and the
   agent request.

See [execution capabilities](../concepts/execution-capabilities.md) and
[harness stamping](../concepts/harness-stamping.md).

## Choose one starting path

### Python SDK execution

Construct typed Environment, Verifier, Task, AgentDefinition, and Job revisions.
Run the Job through the durable scheduler. Follow the
[Python walkthrough](../tutorials/sdk-walkthrough.md).

### Package execution

Configure `EnvironmentManifest`, standalone Verifier and Task revisions, an
optional `HarnessPackage`, `AgentDefinition`, and optionally
`BenchmarkDefinition`. A `JobSpec` selects a Task or Benchmark. Start with the
[CLI walkthrough](../tutorials/cli-walkthrough.md).

The native path (`AgentDefinition.harness is None`) exposes Environment actions to
the model via `native.actions.v1` or `native.chat.v1`. Stamped declared
harnesses are refused at preflight.

### Hosted objects in Plural Intel

Use the hosted APIs exposed by your compatible deployment to publish and fetch
revisioned Environments, Agents, Tasks, Verifiers, and Benchmarks.

## What can the agent do?

Read the environment's native actions and instructions. If a harness is
stamped, read the grant matrix (`plural env harness capabilities`) — not
the harness's declared set. `network=none` removes web search, browser,
network fetch, and MCP from every stamp.

Preflight uses the same effective-policy rules as execution. The local target
is excluded when the Environment requires network isolation, persistence,
compose, or resource limits.

## Local versus hosted changes

Saving a dataset or running a local Job does not publish it. Publishing happens
through an explicit SDK or CLI operation. Changing a local package does not
update already-pinned Task, Agent, or Benchmark revisions.

Eval mode runs final Verifiers but disables Rewarders and TITO capture. Train
mode enables Environment Rewarders and requires exact TITO support. TITO is
saved as hashed artifacts, not embedded in trace JSON.
