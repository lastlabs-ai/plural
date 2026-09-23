---
route: /docs/project/updating
title: Updating and versioning
order: 75
description: Update your project while preserving the versions and results behind earlier comparisons.
audience: all
nav: false
nav_group: Build
---
# Updating and versioning

Edit the files in a Plural project on your machine, then save a version when you
want that setup recorded. A saved version is current immediately. Earlier runs
keep the version they started with.

If you change a support policy, for example, save a new Environment version,
update the affected Tasks, and save a new Benchmark version. Earlier results
still describe the earlier policy.

## Local files

The resource directories in your project are the working copy until you push
them. Edit them, then check the result with `plural <kind> validate <name>`,
which also checks everything the resource depends on. `plural run` always uses
the local files unless you pass `--hosted`. Created SDK models are frozen
values, so in Python construct a new value rather than mutating an instance.

Every manifest's `version` defaults to `0.1.0`. In Python, Environment,
Harness, Agent, Verifier, and Task default to `0.1.0`, and `Benchmark` requires
an explicit version. A content hash includes the resolved fields and the
dependencies a resource references. Editing source or configuration creates a
different hash even if the version string is unchanged.

Do not compare two meanings under the same version.

## Versions

Saving in the web app, or pushing with `plural <kind> push`, records a version as
an immutable revision in the hosted project and makes it current. The revision
is available in the project immediately and stays private to it. The web app
increments the last number (`1.0.0` becomes `1.0.1`); from the CLI you set
`version` in the manifest. Pushing the same version and the same content again
reuses the existing revision. A push is refused, before anything is uploaded,
when the content changed but the version did not, or when the same content was
already pushed under another version.

Saved versions are immutable:

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

Update dependents from the bottom up. Manifests refer to one another by name,
so an Environment update changes the hash of every Task that uses it, which
changes the Benchmarks that contain those Tasks. Bump each affected version,
then push the top of the chain with `--with-deps`, which pushes dependencies
first. Without `--with-deps`, every dependency must already be pushed with
identical content. `plural.lock` records the exact revision each pushed
resource pins; commit it. In Python, `benchmark.diff(other)` reports which Tasks
changed between two Benchmark versions, and `benchmark.export()` captures every
resource the Benchmark resolves to.

A resource's display details in the hosted project, such as its description on
the resource page, can change without rewriting the content of any saved
revision.

## Jobs and run records

`plural run` creates a new Job every time, under `.plural/jobs/<job-id>/`, and
records the version and content hash of every input it used. The Job's
`config.json` and `lock.json` are written when it is planned and never change. `plural job rerun`
and `plural trial rerun` run those pinned inputs again as a new Job linked to
the original, even if the project files have changed since.

One Trial is an Agent × Task × planned attempt. A retry appends another
numbered execution under the same Trial. Each execution's receipt, logs,
artifact manifest, and artifact bytes are immutable evidence. Do not edit them
in place; an edit breaks the recorded digest and provenance.

The Trial's `selected.json` and the Trial and Job `result.json` summaries may
change as retries or reviews complete. The receipt, logs, artifact manifest, and
artifact bytes they summarize never change.

## What may be appended

- progress events;
- retry executions;
- one immutable submission for each pending Human Verifier;
- the hosted resource and revision ids that a push records in `plural.lock`;
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
