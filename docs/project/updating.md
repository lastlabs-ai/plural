---
route: /docs/project/updating
title: Updating and versioning
order: 75
description: Know what can change in source, what needs a new published version, and which Job, Trial, review, and artifact records are append-only.
audience: all
nav: true
nav_group: Build
---
# Updating and versioning

Plural separates editable source from immutable evidence.

## Before publication

Python and YAML files are drafts: edit them, rebuild packages, and validate
again. Created SDK models are frozen values, so construct a new value rather
than mutating an instance.

Every Environment, Harness, Agent, Verifier, and Task defaults to version
`0.1.0`; Benchmark requires an explicit version. A content hash includes the
resolved fields and pinned dependencies. Editing source or configuration and
reloading creates a different hash even if the version string is unchanged.

That is useful while drafting, but do not compare or publish two meanings under
the same version.

## After publication

Published revisions are immutable:

- Environment changes, including source, Runtime, actions, resources, or
  policy, require a new Environment version.
- Harness code or declarations require a new Harness version and digest.
- Agent model, instructions, routing, secret grants, or Harness changes require
  a new Agent version.
- Verifier command, criteria, evidence, Runtime, or weight changes require a new
  Verifier version.
- Task instructions, data, resources, initial State, Environment, or Verifiers
  require a new Task version.
- Any changed Task pin, order, primary metric, description, or metadata
  requires a new Benchmark version.

Repin dependents from the bottom up. For example, an Environment update changes
the Task hash, which changes its Benchmark pin. `Benchmark.diff()` reports that
chain at the Task boundary; `Benchmark.export()` captures the full resolved
graph.

Hosted parent display metadata may be updated by service APIs, but that does
not rewrite published revision content.

## Jobs and run records

A Job's source, Agents, mode, and attempts determine its stable Trial set.
Planning writes immutable `config.json` and `lock.json`. Change the
configuration to create a different Job identity.

One Trial is an Agent × Task × planned attempt. A retry appends another
numbered execution under the same Trial. Each execution's receipt, logs,
artifact manifest, and artifact bytes are immutable evidence. Do not edit them
in place; an edit breaks the recorded digest and provenance.

The selected execution pointer and execution, Trial, and Job result projections
may advance as retries or reviews complete. The receipt, logs, manifest, and
artifact bytes underneath those projections remain immutable.

## What may be appended

- progress events;
- retry executions;
- one immutable submission for each pending Human Verifier;
- hosted synchronization metadata;
- derived exports copied to new locations.

A review can resolve `awaiting_review` and update aggregate results. It cannot
change model actions, earlier verifier outcomes, receipt pins, or artifact
bytes. The local store rejects a second submission for the same Human
Verifier.

## Resources versus artifacts

An authored `Resource` belongs to an Environment or Task and contributes to its
owner's hash. Update it by creating a new owner version.

A run artifact is output captured from an execution. Its manifest records path,
media type, role, size, and SHA-256 digest. It cannot be updated. Produce a new
execution or an explicitly derived export instead.
