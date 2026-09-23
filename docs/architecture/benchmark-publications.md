---
route: /docs/architecture/benchmark-publications
title: Benchmark publications
order: 1910
description: Maintainer contract for published Benchmark releases, result snapshots, the public manifest, and the future marketplace boundary.
audience: maintainers
nav: false
---
# Benchmark publications

This document is the contract for publishing a Benchmark release with results.
The SDK defines the release rules (`plural.benchmarks.rules`), result
aggregation (`plural.benchmarks.results`), and the public manifest
(`plural.benchmarks.publication`). The hosted service persists them and serves
the public pages. For the author-facing guide, see
[Benchmarks](../project/benchmarks.md#publish-a-release-with-results).

Publication is the only way a Benchmark release or its results become public.
Pushing a Benchmark, or running it, keeps everything private to its project.
A publisher publishes explicitly in the web app, after a preview of exactly what
becomes public, and no CLI command publishes.

## Identity

| Concept | Identity | Mutable |
| --- | --- | --- |
| Benchmark | Stable id and slug | Name and description only |
| Release | One Benchmark version: `content_hash` over its Task pins and release rules | Never |
| Track | `id@version` with a `rules_hash` over every rule except name and description | Never; a rule change is a new version |
| Configuration | The Agent revision's `content_hash` | Never |
| Result | A snapshot of one configuration on one release and track, from named Jobs | Status only: accepted, withdrawn, superseded |
| Manifest | `sha256` digest of its canonical JSON | Never |

A release reference is `plural:benchmark/<slug>@<version>#<digest>`. It names
one manifest, so a consumer can later say exactly which evidence it used.
Corrections, withdrawals, and accepted submissions write a new manifest with the
next `sequence` for the same release; earlier manifests stay readable at
`/api/v1/public/benchmark-manifests/{digest}`.

## What a result is

A result is never computed from "all runs of this Benchmark". It is computed from
the Jobs a publisher names, which must have run on the same release and on the
same track version, with the same Agent revision. Jobs record their track at
creation, and a Job whose Agents do not conform to the track is rejected before
it runs. Jobs without a track, including every Job created before tracks existed,
are shown as legacy evidence: visible, never ranked, never publishable.

Aggregation is defined once, in `aggregate_configuration`: attempts are averaged
within a Task, then Tasks are combined by the release's weights. Attempts are
classified as scored, Agent failure, infrastructure error, cancelled, or pending.
Coverage, completion, success, uncertainty, cost, and latency are reported with
their denominators. Results rank only on the Verifier `score`; per-step rewards
are not an input.

A configuration that falls back to another model, or reports calling more than
one model, is a system. It can rank on an Agents track. A Models track rejects
a configured fallback when the Job is created, and marks an entry not ranked
when its attempts reported calling another model, so a multi-model score is
never credited to one model. Configured
and actually-called models are both recorded (`trials.usage.models_used`).

## Provenance

- **Plural-executed**: the Trials ran on Plural and are linked from the result.
- **Independently reproduced**: another project re-ran the configuration on the
  same release and track.
- **Self-reported**: the submitter ran it elsewhere and reported per-attempt
  scores. The publisher reviewed it; Plural did not run it.
- **Legacy**: no track was recorded. Never ranked.

Provenance describes how a result was produced. It is not a statement about the
quality of the Benchmark.

## The public boundary

The manifest carries only public routing metadata:

- publication, publisher, release, track, configuration, and result identifiers;
- Task names, descriptions, categories, applicability, and requirements;
- score semantics: range, success threshold, weights, and Verifier names and kinds;
- per-Task and per-category scores, coverage, sample counts, and uncertainty;
- measured cost and latency with units and denominators;
- provenance, evaluation dates, lineage, license, and correction status.

It never carries private evaluation material: a Task's initial State and reset
options, Verifier definitions, rubrics, and expected outputs, resource contents,
secrets, or trace contents. Task instructions and Verifier findings on example
attempts are included only when the publisher chooses, after a preview that
lists what stays private. The manifest states this boundary in its `boundary`
field. No manifest, Verifier output, or score is ever placed in an evaluated
Agent's context.

## Categories and comparability

Categories have stable ids. An optional `taxonomy` id such as
`plural:coding/refactoring` lets a future consumer align categories across
publications, but alignment does not make scores comparable: each score is only
meaningful within its release, track, and score semantics. There is no
universal capability score.

## Future marketplace integration points

The marketplace will be published Benchmarks with granular results, which a
future router references explicitly. These are the integration points; none of
the router, payments, or payouts exist yet.

- **Selection**: a router is configured with release references, not Benchmark
  names, so a republished release never silently changes its evidence.
- **Lookup**: the router reads per-Task and per-category results, applicability,
  and requirements from the manifest to match a request to evidence.
- **Attribution**: each routing decision should record the release reference,
  the result ids it relied on, and the publisher id. Those are stable today.
- **Corrections**: a router must re-read the latest manifest for a release and
  stop using withdrawn or superseded results.

## Unresolved incentive decisions

Here, incentives means payouts to publishers and submitters, not per-step
rewards. Payouts should follow useful, trusted evidence and real usage, never
submission volume or favourable scores. Still open:

- how usage is measured: routing decisions, served requests, or revenue share;
- how credit splits between a Benchmark's publisher and the submitters of the
  results a decision used;
- how much weight each provenance earns, and how reproduction is paid;
- how withdrawn or corrected evidence affects payouts already attributed;
- how to prevent gaming: duplicate Benchmarks, self-dealing between publisher
  and model owner, and Tasks tuned to favour one configuration;
- whether private Benchmarks can contribute evidence without publishing Tasks.
