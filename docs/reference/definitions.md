---
route: /docs/reference/definitions
title: "Definitions"
order: 200
description: "Reference for the seven public evaluation objects and their shared Python, YAML, and CLI semantics."
audience: all
nav: false
---
# Definitions

Public models reject unknown fields and use ordinary semantic versions.
Environment, Agent, Verifier, and Task default to `0.1.0`; Benchmark requires an
explicit version.

## Objects

- `Environment`: world, Runtime, actions, resources, limits, and rendering.
- `Runtime`: isolation, image, compute, filesystem, network, secrets, placement.
- `Agent`: model, provider, instructions, optional Harness, metadata.
- `Verifier`: information, criteria, evidence, runtime, weight, check behavior.
- `Task`: instructions, Environment, Verifiers, resources, initial state.
- `Benchmark`: name, version, ordered Tasks, primary metric, metadata.
- `Job`: source, Agents, mode, attempts, concurrency, retry policy.

## Serialization

`plural.project.Resolver` is the only resolver. It accepts YAML files and
`path.py:object` references. `load`, `dump`, and `dumps` are convenience
functions over the same implementation.

YAML field names, defaults, and nesting match public constructors. Resolved
Python and YAML graphs preserve content hashes and plans.

## Catalog context

`CatalogContext` carries an effective `ModelCatalog` to Agent factories,
Verifier factories, loaders, CLI commands, and Job planning. It never changes
global state.

Generated schema files use plain public names such as `Agent.schema.json`,
`Task.schema.json`, and `Job.schema.json`.
