---
route: /docs/concepts/execution
title: "Packages, jobs, and trials"
order: 160
description: "Plural schema v2 separates authoring identity from execution identity. A Job selects either a Task revision or a Benchmark revision, then expands Agents × Tasks × attempts into Trials. A retry is a new TrialExecution under the same Trial id"
audience: all
---
# Packages, jobs, and trials

Plural schema v2 separates authoring identity from execution identity. A Job
selects either a Task revision or a Benchmark revision, then expands Agents ×
Tasks × attempts into Trials. A retry is a new TrialExecution under the same
Trial identity.

## Ownership

An **Environment** owns its overview, actions, hidden state and
observable schemas, train-only Rewarders, resources, secrets policy, and
runtime placement. It never owns Tasks, Verifiers, or run mode.

A **Task** pins one Environment revision and one or more weighted Verifier
revisions. Task instructions and `info` are injected into the Agent request.
A **Verifier** is deterministic, agent, or human, and deterministic/agent
Verifiers declare runtime and connectivity independently from the Environment.

A **HarnessPackage** declares implementation (`declared` or `runnable`),
capabilities, and a command. A **HarnessGrant** is resolved per Trial against
that Task's Environment.

An **AgentDefinition** owns model, instructions, routing, and an optional
Harness. It does not bind to an Environment. A **BenchmarkDefinition** selects
Task revisions and may span Environments.

`agents × selected tasks × attempts = trials`

Every Trial uses `task.environment.runtime.provider` and immutable placement.
Job concurrency is only a scheduling ceiling and cannot override Environment
runtime, network, resources, or secrets.

## Preflight

`resolve_effective_policy()` intersects provider, project, environment,
harness, and agent layers. Unsupported requirements raise
`CapabilityError` before any sandbox is created.

Eval mode disables Rewarders and TITO capture but still runs final Verifiers.
Train mode requires exact artifact-backed TITO support and enables Rewarders.
Human Verifiers move the Trial to `awaiting_review`.

Jobs and TrialExecutions append monotonic `ProgressEvent` records. Use
`plural job watch JOB_ID --json` or `plural trial watch TRIAL_ID --job JOB_ID`.

See [execution capabilities](execution-capabilities.md).
