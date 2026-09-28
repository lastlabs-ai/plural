---
route: /docs/reference/definitions
title: "Definitions"
order: 200
description: "The eight objects Plural is built from, what each one holds, and how they behave the same way in Python, YAML, and the CLI."
audience: all
nav: false
---
# Definitions

Plural is built from eight objects. You describe six of them yourself: the world, the
assignment, the grader, the contestant, how the contestant plays, and the exam. Plural
creates the other two, the run and each attempt, when you run something.

This page lists what each object holds. It is a reference, so it is brief. For a
friendly introduction with examples, read [Core concepts](../getting-started/concepts.md)
first.

## Objects

In everyday terms first, then the fields each one holds:

| Everyday idea | Object | What it holds |
| --- | --- | --- |
| The world | `Environment` | world, actions, state, observation, Runtime, resources, rewarders, limits, and rendering |
| One assignment | `Task` | instructions, one Environment, Verifiers, task resources, initial state |
| The grader | `Verifier` | information, criteria, evidence, runtime, weight, check behavior |
| The contestant | `Agent` | model, provider, instructions, optional Harness, metadata |
| How the contestant plays | `Harness` | interaction loop and extra tools for one Agent, bounded by the Environment's policy |
| The exam | `Benchmark` | name, version, ordered Tasks, scoring rules, and metadata |
| One run you start | `Job` | source, Agents, mode, attempts, concurrency, retry policy |
| One attempt | `Trial` | one Agent × one Task × one planned attempt; Job output |

Runtime, Resources, and Rewarders are part of the Environment. They are not objects of
their own.

A few rules that matter:

- **Agent:** with no Harness, an Agent uses `native`, Plural's built-in tool loop.
- **Harness:** `Harness` is the base class you subclass to write one;
  `HarnessDefinition` is the flattened public schema that describes a packaged Harness
  in YAML and the API.
- **Benchmark:** it ranks only on the Verifier `score` (`primary_metric` defaults to
  `"score"`); rewards never contribute.

## Versions and strict fields

Every object you write has a version number, and Plural rejects fields it does not
recognize, so a typo fails loudly instead of being ignored.

Precisely: public models reject unknown fields and use ordinary semantic versions.
Environment, Agent, Harness, Verifier, and Task default to `0.1.0`. The Python
`Benchmark` requires an explicit version, and a `benchmark.yaml` defaults to `0.1.0`
like every other manifest.

## Project manifests

In a project, each of the first six objects is a folder with one settings file in it.
The folder's name is the object's name.

Precisely: each resource is one directory holding one manifest: `environment.yaml`,
`task.yaml`, `verifier.yaml`, `harness.yaml`, `agent.yaml`, or `benchmark.yaml`.
Manifests reference other resources by name, Python behavior as `file.py:Object`, and
files by paths inside the resource directory. Other field names, defaults, and nesting
match the public constructors.

`plural.project.Workspace` is the only loader. It reads a manifest, validates the
resource and its dependencies, and returns the SDK object; the CLI uses the same code.
Jobs and Trials have no manifest: `plural run` or a Python `Job` creates them. The JSON
Schemas for every manifest are in [project-schemas.json](../assets/project-schemas.json).
See [YAML and serialization](../interfaces/yaml.md).

## Catalog context

This is for Python users who add their own models. A catalog context makes sure every
Agent, grader, and run you create from it looks models up in the same list.

Precisely: `CatalogContext` carries one `ModelCatalog`, including any model entries you
add for your project, to the Agents and Verifiers you create from it, to a `Workspace`
loading project resources, and to Job planning, so they all resolve models the same
way. It never changes global state. See the
[Python SDK guide](../sdk/evaluation.md#load-project-resources).
