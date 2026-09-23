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
Environment, Agent, Harness, Verifier, and Task default to `0.1.0`; the Python
`Benchmark` requires an explicit version, and a `benchmark.yaml` defaults to
`0.1.0` like every other manifest.

## Objects

Eight objects. Runtime, Resources, and Rewarders are nested inside the
Environment; they are not top-level objects.

- `Environment`: world, actions, state, observation, Runtime, resources,
  rewarders, limits, and rendering.
- `Task`: instructions, one Environment, Verifiers, task resources, initial
  state.
- `Verifier`: information, criteria, evidence, runtime, weight, check behavior.
- `Agent`: model, provider, instructions, optional Harness, metadata. With no
  Harness, an Agent uses `native`, Plural's built-in tool loop.
- `Harness`: interaction loop and extra tools for one Agent, bounded by the
  Environment's policy. `Harness` is the base class you subclass to write one;
  `HarnessDefinition` is the flattened public schema that describes a packaged
  Harness in YAML and the API.
- `Benchmark`: name, version, ordered Tasks, scoring rules, and metadata. It
  ranks only on the Verifier `score` (`primary_metric` defaults to `"score"`);
  rewards never contribute.
- `Job`: source, Agents, mode, attempts, concurrency, retry policy.
- `Trial`: one Agent × one Task × one planned attempt; Job output.

## Project manifests

The first six objects are saved in a project as one directory per resource,
each holding one manifest: `environment.yaml`, `task.yaml`, `verifier.yaml`,
`harness.yaml`, `agent.yaml`, or `benchmark.yaml`. The directory name is the
resource's name. Manifests reference other resources by name, Python behavior
as `file.py:Object`, and files by paths inside the resource directory. Other
field names, defaults, and nesting match the public constructors.

`plural.project.Workspace` is the only loader. It reads a manifest, validates
the resource and its dependencies, and returns the SDK object; the CLI uses the
same code. Jobs and Trials have no manifest: `plural run` or a Python `Job`
creates them. The JSON Schemas for every manifest are in
[project-schemas.json](../assets/project-schemas.json). See
[YAML and serialization](../interfaces/yaml.md).

## Catalog context

`CatalogContext` carries one `ModelCatalog`, including any model entries you add
for your project, to the Agents and Verifiers you create from it, to a
`Workspace` loading project resources, and to Job planning, so they all resolve
models the same way. It never changes global state. See the
[Python SDK guide](../sdk/evaluation.md#load-project-resources).
