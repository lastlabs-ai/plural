---
route: /docs/project/updating
title: Updating and versioning
order: 75
description: Change your project freely while every earlier result keeps pointing at the exact setup it was measured on.
audience: all
nav: false
nav_group: Build
---
# Updating and versioning

You can keep editing your project as your work changes. Plural makes sure every
earlier result still points at the exact setup it was measured on, so an old score
never quietly takes on a new meaning.

The idea is the same as editions of a textbook. You can write a second edition, but
the first edition on the shelf does not change, and a grade earned on it still refers
to it.

## Why it matters

Say your support policy changes. You save a new Environment version with the new
policy, update the affected Tasks, and save a new Benchmark version. Results from
last month still describe last month's policy, and new results describe the new one.
Nothing gets mixed up.

Here is the short version of how it works:

- Your files on your computer are a **working copy**. Edit them as much as you like.
- When you want to record a setup, you **save a version**. A saved version is current
  immediately and never changes afterwards.
- Every run remembers the exact versions it used. Earlier runs keep the versions they
  started with.

## Local files

The resource folders in your project are the working copy until you push them. Edit
them, then check the result:

```bash
plural env validate support-triage
plural benchmark validate support-triage
```

`plural <kind> validate <name>` also checks everything the resource depends on.
`plural run` uses your local files unless you pass `--hosted` or
[name a retained version](#calling-a-version-by-name). In Python, created SDK objects
are frozen values, so construct a new value rather than changing an existing one.

Every manifest's `version` defaults to `0.1.0`. In Python, Environment, Harness,
Agent, Verifier, and Task default to `0.1.0`, and `Benchmark` requires an explicit
version.

Plural also keeps a **content hash** for each resource: a fingerprint of its resolved
fields and of the resources it refers to. Editing source or configuration creates a
different hash even if the version string is unchanged.

> **Good to know:** Do not give two different setups the same version. One version
> should always mean one thing.

## Versions

Saving in the web app, or pushing with `plural <kind> push`, records a version as an
immutable revision (a saved snapshot) in the hosted project and makes it current. The
revision is available in the project immediately and stays private to it.

- The web app increments the last number: `1.0.0` becomes `1.0.1`.
- From the command line, you set `version` in the manifest yourself.
- Pushing the same version and the same content again reuses the existing revision.
- A push is refused, before anything is uploaded, when the content changed but the
  version did not, or when the same content was already pushed under another version.

A resource's display details in the hosted project, such as its description on the
resource page, can change without rewriting the content of any saved revision.

### What needs a new version

Saved versions are immutable. These changes each need a new version:

- **Environment**: source, Runtime, actions, resources, or policy.
- **Harness**: code or declarations need a new Harness version and digest.
- **Agent**: model, instructions, routing, secret grants, or Harness.
- **Verifier**: command, criteria, evidence, Runtime, or weight.
- **Task**: instructions, data, resources, initial State, Environment, or Verifiers.
- **Benchmark**: any changed Task pin, order, primary metric, description, or
  metadata.

### Update from the bottom up

Resources refer to each other by name, so a change ripples upward. An Environment
update changes the hash of every Task that uses it, which changes the Benchmarks that
contain those Tasks.

1. Bump each affected version, starting with the one you changed.
2. Push the top of the chain with `--with-deps`, which pushes dependencies first:

```bash
plural benchmark push support-triage --with-deps
```

Without `--with-deps`, every dependency must already be pushed with identical
content. `plural.lock` records the exact revision each pushed resource pins; commit
it to version control.

In Python, `benchmark.diff(other)` reports which Tasks changed between two Benchmark
versions, and `benchmark.export()` captures every resource the Benchmark resolves to.

## Calling a version by name

Every pushed version stays in the hosted project, so `name@version` keeps naming one
exact revision after your files move on. Use it wherever a command names a Task,
Benchmark, or Agent to run, show, or pull:

```bash
plural run --benchmark wordlebench@0.1.1 --model openai/gpt-5.6-luna
plural run --task refund@0.1.0 --agent baseline@0.2.0 --hosted
plural benchmark show wordlebench@0.1.1
plural benchmark pull wordlebench@0.1.1 --force
```

What happens when you run one:

- If your working copy already is that version, with no unpushed edits, the run uses
  it.
- Otherwise `plural run` restores the version, and the exact revisions it pins, under
  `.plural/versions/` and runs that copy. Your working files are never touched, and the
  Job lands in `.plural/jobs` like any other.
- An input you name without a version, such as `--agent baseline` beside
  `--benchmark wordlebench@0.1.1`, still comes from your working copy.

Restoring needs a signed-in, registered project. A version that was never pushed
cannot be recalled.

`plural <kind> show name@version` shows that one revision, and
`plural <kind> pull name@version` replaces the working copy with it, keeping a backup
of files that differ.

The web app takes the same form: open `/benchmarks/wordlebench@0.1.1` to see that
version's leaderboard. The API resolves a version wherever it takes a revision id, as
in `GET /api/v1/benchmarks/wordlebench/revisions/0.1.1`.

## Going deeper

The rest of this page describes exactly what Plural records for each run, and what
can and cannot change afterwards. Most readers can stop here.

### Jobs and run records

`plural run` creates a new Job every time, under `.plural/jobs/<job-id>/`, and records
the version and content hash of every input it used. The Job's `config.json` and
`lock.json` are written when it is planned and never change. `plural job rerun` and
`plural trial rerun` run those pinned inputs again as a new Job linked to the
original, even if the project files have changed since.

One Trial is one Agent, on one Task, for one planned attempt. A retry appends another
numbered execution under the same Trial. Each execution's receipt, logs, artifact
manifest, and artifact bytes are immutable evidence. Do not edit them in place; an
edit breaks the recorded digest and provenance.

The Trial's `selected.json` and the Trial and Job `result.json` summaries may change
as retries or reviews complete. The receipt, logs, artifact manifest, and artifact
bytes they summarize never change.

### What may be appended

Records only ever grow. These are the things that may be added:

- progress events;
- retry executions;
- one immutable submission for each pending Human Verifier;
- the hosted resource and revision ids that a push records in `plural.lock`;
- derived exports copied to new locations.

A review can resolve `awaiting_review` and update aggregate results. It cannot change
model actions, earlier verifier outcomes, receipt pins, or artifact bytes. The local
store rejects a second submission for the same Human Verifier.

### Resources versus artifacts

An authored `Resource` is a file you provide, such as a word list or a policy
document. It belongs to an Environment or Task and contributes to its owner's hash.
Update it by creating a new owner version.

A run artifact is output captured from an execution. Its manifest records path, media
type, role, size, and SHA-256 digest. It cannot be updated. Produce a new execution or
an explicitly derived export instead.
