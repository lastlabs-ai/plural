---
route: /docs/reference/definitions
title: "Definitions"
order: 200
description: "Reference for the eight public evaluation objects and their shared Python, YAML, and CLI semantics."
audience: all
nav: false
---
# Definitions

Public models reject unknown fields and use ordinary semantic versions.
Environment, Agent, Verifier, and Task default to `0.1.0`; Benchmark requires an
explicit version.

## Objects

Eight objects. Runtime, Resources, and Rewarders are nested inside the
Environment; they are not top-level objects.

- `Environment`: world, actions, state, observation, Runtime, resources,
  rewarders, limits, and rendering.
- `Task`: instructions, one Environment, Verifiers, task resources, initial
  state.
- `Verifier`: information, criteria, evidence, runtime, weight, check behavior.
- `Agent`: model, provider, instructions, optional Harness, metadata.
- `Harness`: interaction loop and extra tools for one Agent, bounded by the
  Environment's policy.
- `Benchmark`: name, version, ordered Tasks, primary metric, metadata.
- `Job`: source, Agents, mode, attempts, concurrency, retry policy.
- `Trial`: one Agent × one Task × one planned attempt; Job output.

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
