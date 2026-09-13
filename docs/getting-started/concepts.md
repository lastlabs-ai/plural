---
route: /docs/getting-started/concepts
title: Understand the pieces
order: 1114
description: Learn the seven public evaluation concepts and how Python, YAML, and CLI references resolve to one semantic graph.
audience: all
nav: false
---
# Understand the pieces

- **Environment**: state, observations, actions, resources, and limits.
- **Runtime**: image, compute, filesystem, network, secrets, and placement.
- **Agent**: catalog model, instructions, provider preference, and optional Harness.
- **Verifier**: deterministic, model, or human assessment of a completed Trial.
- **Task**: instructions, one Environment, and one or more Verifiers.
- **Benchmark**: a versioned ordered list of pinned Tasks.
- **Job**: a Task or Benchmark, Agents, mode, attempts, and retry policy.

A Job expands to Agent × Task × attempt Trials. Runtime retries do not create a
different Trial. Rewarders produce transition signals in train mode; Verifiers
score completed Trials.

Python constructors own defaults and validation. YAML uses the same field names
and nesting. The CLI only resolves references and invokes public methods.

Routing and tracing consume evaluation records, but they are secondary to this
seven-concept authoring path.
