---
route: /docs/architecture/revision-identity
title: Revision identity
order: 1950
description: Maintainer specification for how a revision is identified, numbered, labeled, and linked, so every SDK and the service agree.
audience: maintainers
nav: false
---
# Revision identity

Every saved revision of an Environment, Verifier, Task, Harness, Agent, or Benchmark
is identified by a **content hash**: a fingerprint of what the revision contains and
nothing else. The service also gives each revision a **number** in the order it was
pushed, and optionally a **release version** that people choose. This page specifies
all three, so that an SDK in any language computes the same hash as the Python SDK
and the service.

`spec/identity/vectors.json` in the SDK repository holds test vectors. An
implementation is conforming when it reproduces every one of them.

## The three names of a revision

| Name | Example | Chosen by | Unique within | Changes when |
| --- | --- | --- | --- | --- |
| Content hash | `sha256:61d8…` | Nobody: computed | Everything | Content changes |
| Number | `#3` | The service, in push order | One resource | Never |
| Release version | `1.2.0` | A person, with `release` | One resource | Never, once given |

Content decides identity. Two revisions with the same content are the same revision:
pushing content a resource already holds makes that existing revision current again
instead of adding a duplicate. Numbers and versions are labels on top. Neither
contributes to the hash, so renaming a resource, releasing it as `1.2.0`, or forking it
into another project keeps its hash.

## Content hash

```text
revision_hash(kind, content) =
    "sha256:" + hex(SHA-256(UTF-8(JCS({"identity": 2, "kind": kind, "content": body}))))
```

- **`identity`** is the version of these rules. It is hashed in, so a future change to
  the rules can never produce a hash that collides with one made under these.
- **`kind`** is one of `environment`, `verifier`, `task`, `harness`, `agent`, or
  `benchmark`. The same content under two kinds has two hashes.
- **`body`** is the revision's canonical definition with the top-level label fields
  `name`, `title`, `version`, and `revision` removed. Only top-level keys are removed;
  a nested object keeps a `name` it contains.
- **JCS** is the JSON Canonicalization Scheme,
  [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785): object keys sorted by UTF-16
  code units, no insignificant whitespace, strings escaping only what JSON requires,
  and numbers in the shortest ECMAScript form, so `1.0` and `1` serialize alike. Keep
  integers within ±(2⁵³ − 1) so every language reads them the same.

Before canonicalizing, arrays under these keys, at any depth, are sets and are sorted
by the canonical JSON of their elements: `allowed_capabilities`,
`allowed_harness_capabilities`, `allowed_targets`, `capabilities`, `declared`,
`denied`, `denied_capabilities`, `enforced`, `extra_capabilities`, `granted`,
`granted_harness_capabilities`, and `targets`. Every other array keeps its order,
because order carries meaning, as in a Benchmark's Task list.

### Dependencies enter by hash

A revision refers to what it depends on by that dependency's content hash, never by
name, id, or version:

- A **Task** holds its Environment's hash and one hash per Verifier.
- An **Agent** holds its Harness's hash.
- A **Benchmark** holds one hash per Task.

A Benchmark's hash therefore covers every Task, Environment, and Verifier beneath it,
and changing an Environment changes the hash of every Task and Benchmark above it.

### Source files

An Environment, Verifier, or Harness carries code. Its definition includes a
**source digest** of its directory:

```text
source_digest = "sha256:" + hex(SHA-256(
    for each file, in order: UTF-8(relative path) ‖ 0x00 ‖ bytes ‖ 0x00
))
```

- Paths are relative to the resource directory and use `/`.
- Files are ordered by comparing paths **component by component**, each component as
  a string: `a/one.py` sorts before `a-b.txt`, because the component `a` sorts before
  `a-b.txt`.
- The manifest at the root (`environment.yaml`, `verifier.yaml`, `harness.yaml`,
  `task.yaml`, `agent.yaml`, `benchmark.yaml`) is left out. Its settings already reach
  the hash through the parsed definition, and its `name`, `title`, and `version` lines
  are labels.
- `.git`, `.plural`, `__pycache__`, and every path listed in the directory's
  `.pluralignore` are left out. A symbolic link anywhere in the tree is an error.

A package's **archive digest**, the SHA-256 of the uploaded archive's bytes, is
separate. It proves an upload arrived intact and plays no part in identity.

## Numbers and release versions

The service numbers a resource's revisions `1, 2, 3, …` in push order. A number is
never reused, even after the revision it named is superseded.

A release version is optional. It starts with a letter or digit, continues with
letters, digits, `.`, `+`, `_`, or `-`, is at most 64 characters, and is never only
digits, so that it cannot be read as a number. Once a
version names a revision it names that revision forever: it cannot move to another
revision, and a revision cannot be given a second one.

A push may ask for a version, as a manifest's `version:` line does. The service
applies it to a new revision only when the version is still free and valid; otherwise
the revision is saved without one, and the CLI says which revision already holds the
version. `plural <kind> release NAME VERSION` gives an existing revision a version,
and publishing a Benchmark requires one.

People read a revision as `#3`, or `#3 (1.2.0)` once it is released.

## Selecting a revision

Everywhere a revision is named after `@`, in the CLI, in web links, and in the API's
revision paths, the service and every SDK accept:

| Selector | Example | Selects |
| --- | --- | --- |
| Number | `wordle@3`, `wordle@#3` | Revision #3 |
| Release version | `wordle@1.2.0` | The revision released as 1.2.0 |
| Content hash | `wordle@sha256:61d8a0c` | The revision with that hash; a prefix of at least 7 hex digits must match exactly one |
| Revision id | the id | That revision |

No selector means the current revision.

## Concurrent edits

A push states the revision it was edited from as `parent_revision_id`. When that is no
longer the resource's current revision, someone else pushed in between, and the push
is refused with `409 Conflict` so their work is never silently layered over. Pull the
new revision and reapply the change, or push with `force` to add it on top. Pushing
content the resource already holds is never refused, because it adds nothing.

## Lineage

The service records where each revision came from as typed links from the new
revision to its source:

- **`edited_from`**: the revision a push was edited from, recorded from
  `parent_revision_id`.
- **`forked_from`**: a revision of the same kind, possibly in another project of the
  same account, that this one was copied from.
- **`derived_from`**: a revision of any kind that this one was built from, such as an
  Environment derived from an Agent's traces.

`GET /api/v1/<collection>/<id>/revisions/<revision>/lineage` returns a revision's
sources and the revisions derived from it. Lineage is history, not identity: a link
never changes a hash.

## Sealed and referenced kinds

Environments, Verifiers, Tasks, Harnesses, and Benchmarks are **sealed**: their hash
covers everything that decides how they behave, so a revision behaves the same every
time it runs. An Agent is **referenced**: it names a hosted model, which its provider
can change without the Agent's hash changing. The API marks each resource with
`sealed`, and results should treat an Agent's revision as a description of what was
asked for, not a guarantee of what answered.

## Earlier hashes

Revisions saved before identity scheme 2 were rehashed under these rules. Each keeps
its earlier hash as `legacy_content_hash`, and anything that selects or verifies a
revision by hash accepts either, so pins recorded before the change still resolve.
