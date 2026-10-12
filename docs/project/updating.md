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

Say your support policy changes. You save the Environment with the new policy,
update the affected Tasks, and save the Benchmark again. Results from
last month still describe last month's policy, and new results describe the new one.
Nothing gets mixed up.

Here is the short version of how it works:

- Your files on your computer are a **working copy**. Edit them as much as you like.
- When you want to record a setup, you **push** it. Each push that changes something
  saves a numbered **revision**, such as `#4`, which is current immediately and never
  changes afterwards.
- When you want a name people can cite, you **release** a revision as a version, such
  as `1.2.0`.
- Every run remembers the exact revisions it used. Earlier runs keep the revisions they
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
[name a retained revision](#calling-a-revision-by-name). In Python, created SDK objects
are frozen values, so construct a new value rather than changing an existing one.

Plural keeps a **content hash** for each resource: a fingerprint of its resolved
fields and of the content hashes of the resources it refers to. Editing source or
configuration creates a different hash. Names, titles, and versions are labels and
are left out, so renaming a resource keeps its hash. See
[Revision identity](../architecture/revision-identity.md) for the exact rules.

## Revisions and versions

Saving in the web app, or pushing with `plural <kind> push`, records an immutable
revision (a saved snapshot) in the hosted project and makes it current. The revision
is available in the project immediately and stays private to it.

- The hosted project numbers revisions in push order: `#1`, `#2`, `#3`. You never
  bump anything.
- Pushing content the resource already holds reuses that revision and makes it
  current, so undoing an edit and pushing restores the earlier revision.
- A push is refused, before anything is uploaded, when someone else pushed a newer
  revision after the one you edited. Pull theirs and reapply your change, or pass
  `--force`.

A **release version** is an optional, permanent name for one revision:

```bash
plural benchmark release support-triage 1.2.0
```

A version names one revision forever and is never only digits. Publishing a
Benchmark requires one. A `version:` line in a manifest asks for that version on the
next push; it is applied when no other revision already has it.

A resource's display details in the hosted project, such as its description on the
resource page, can change without rewriting the content of any saved revision.

### What makes a new revision

Saved revisions are immutable. Each of these changes makes a new one when you push:

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

Push the top of the chain with `--with-deps`, which pushes every changed
dependency first:

```bash
plural benchmark push support-triage --with-deps
```

Without `--with-deps`, every dependency must already be pushed with identical
content. `plural.lock` records the exact revision each pushed resource pins; commit
it to version control.

In Python, `benchmark.diff(other)` reports which Tasks changed between two Benchmark
revisions, and `benchmark.export()` captures every resource the Benchmark resolves to.

## Calling a revision by name

Every pushed revision stays in the hosted project, so `name@3` or `name@1.2.0` keeps
naming one exact revision after your files move on. After `@`, give a revision
number, a release version, or a content hash of at least 7 hex digits. Use it
wherever a command names a Task, Benchmark, or Agent to run, show, or pull:

```bash
plural run --benchmark wordlebench@1.0.0 --model openai/gpt-5.6-luna
plural run --task refund@2 --agent baseline@sha256:61d8a0c --hosted
plural benchmark show wordlebench@3
plural benchmark pull wordlebench@1.0.0 --force
```

What happens when you run one:

- If your working copy already holds that revision's content, the run uses it.
- Otherwise `plural run` restores the revision, and the exact revisions it pins, under
  `.plural/versions/` and runs that copy. Your working files are never touched, and the
  Job lands in `.plural/jobs` like any other.
- An input you name without a version, such as `--agent baseline` beside
  `--benchmark wordlebench@1.0.0`, still comes from your working copy.

Restoring needs a signed-in, registered project. A revision that was never pushed
cannot be recalled.

`plural <kind> show name@3` shows that one revision, and `plural <kind> pull name@3`
replaces the working copy with it, keeping a backup of files that differ.

The web app takes the same form: open `/benchmarks/wordlebench@1.0.0` or
`/benchmarks/wordlebench@3` to see that revision's leaderboard. The API resolves a
number, version, or hash wherever it takes a revision id, as in
`GET /api/v1/benchmarks/wordlebench/revisions/1.0.0`.

## Going deeper

The rest of this page describes exactly what Plural records for each run, and what
can and cannot change afterwards. Most readers can stop here.

### Jobs and run records

`plural run` creates a new Job every time, under `.plural/jobs/<job-id>/`, and records
the revision and content hash of every input it used. The Job's `config.json` and
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
Update it by pushing a new revision of its owner.

A run artifact is output captured from an execution. Its manifest records path, media
type, role, size, and SHA-256 digest. It cannot be updated. Produce a new execution or
an explicitly derived export instead.
