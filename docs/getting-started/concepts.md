---
route: /docs/getting-started/concepts
title: Core concepts
order: 25
description: Learn the authored evaluation objects, immutable run records, and one execution lifecycle shared by Python, YAML, and CLI.
audience: all
nav: true
nav_group: Start
---
# Core concepts

## What you author

- **Environment:** the world—typed State and Observation, actions, resources,
  Runtime, limits, rendering, and optional Rewarders.
- **Task:** instructions and case data bound to one Environment and one or more
  Verifiers.
- **Verifier:** deterministic code, a judging Agent, or a Human that scores a
  completed Trial from declared evidence.
- **Agent:** a catalog model, instructions, provider preference, and at most one
  optional Harness.
- **Harness:** the model interaction loop. Omit it to use Plural's native loop.
- **Benchmark:** an immutable semantic version that pins an ordered Task set.
- **Job:** a Task or Benchmark, Agents, eval/train mode, attempts, concurrency,
  and retry policy.

## What a run creates

A Job expands to `Agent × Task × attempts` independent **Trials**. A transient
failure can create another **execution** of the same Trial; retries do not
change Trial identity.

Each execution records a receipt, logs, artifacts, and usually a normalized
trajectory. Final Verifiers produce evidence, feedback, and scores. Human
Verifiers pause at `awaiting_review`; review submissions are append-only.

## Episode lifecycle

1. Bind Task data and validate initial state.
2. Reset the Environment.
3. Send the Observation to the Agent.
4. Apply an Agent action and update State.
5. Produce the next Observation and repeat until terminal, truncated, or
   limited.
6. Persist outputs and run final Verifiers.
7. Aggregate Verifier rewards by their `weight`.

State is internal world data. Observation is the Agent-visible projection.
Hidden State is available to a Verifier only when its evidence contract opts
in; operating-system isolation is still the Runtime's responsibility.

Eval mode is the default. Train mode additionally requires exact TITO capture
and may collect Rewarder signals. It does not train a model.

Python is the semantic source. YAML uses identical public fields, and the CLI
adds no separate domain model.
