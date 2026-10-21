---
route: /docs/platform/publish
title: Publish to the Hub
order: 108
description: "Share a Benchmark release and its leaderboard on the Hub: run it on an evaluation track, release a version, choose what becomes public, and review outside submissions."
audience: all
nav: true
nav_group: Platform
outcome: You can publish a Benchmark release with the results you choose, and review results others submit.
---
# Publish to the Hub

The **Hub** is where Benchmarks are shared: anyone can read a published Benchmark's
leaderboard, see which configurations did well on which Tasks, and trace each result
to the evidence it came from. Nothing reaches the Hub until you publish it. Pushing a
Benchmark, or running it, keeps everything private to its project.

Publishing takes four steps.

## 1. Declare a track

An evaluation **track** is a versioned set of rules that makes results comparable,
such as the number of attempts and which Harnesses are allowed. Only results on a
track are ranked or published. Add one to `benchmarks/<name>/benchmark.yaml`:

```yaml
tracks:
  - id: open
    name: Open systems
    kind: agents
    attempts: 2
```

An `agents` track compares complete systems as built. A `models` track holds
everything but the model constant. See
[Declare what a release measures](../project/benchmarks.md#declare-what-a-release-measures)
for every rule a track can set.

## 2. Release a version

A published release needs a version people can cite:

```bash
plural benchmark release support 1.0.0
```

`release` pushes the Benchmark and anything it uses that changed, then names the
resulting revision `1.0.0`. A version names one revision forever.

## 3. Run it on the track

Run each configuration you want on the leaderboard, recorded in the hosted project and
bound to the track:

```bash
plural run --benchmark support@1.0.0 --agent careful --record --evaluation-track open
plural run --benchmark support@1.0.0 --model openai/gpt-5.6-luna --record --evaluation-track open
```

`support@1.0.0` pins the release even after your files move on. The run uses the
track's attempts, and an Agent that breaks the track's rules is refused before
anything runs. The Benchmark's **Leaderboard** tab in the web app ranks each
configuration as its Jobs finish.

## 4. Publish

Open the Benchmark in the web app, go to **Releases**, and choose **Publish** on the
release. The dialog walks through:

1. **Results to publish.** Pick configurations from the leaderboard. Each result is
   frozen from exactly the Jobs it ran in.
2. **What else to disclose.** Task instructions and Verifier findings on example
   attempts are private by default, since both can reveal answers. Traces, Verifier
   definitions, hidden State, resources, and secrets are never published.
3. **Listing.** A title, the page's address, and whether it is listed on the Hub or
   reachable only by link. You also choose whether to accept self-reported
   submissions for review.

Read the preview of exactly what becomes public, then publish. A published release
never changes. It is addressed by a reference such as
`plural:benchmark/support@1.0.0#sha256:…`, so anyone citing it names exactly the
evidence they used. Corrections and withdrawals add to the public history; earlier
versions of the page stay readable.

## Results from others

Others can submit results against an exact release and track. Every submission waits
for your review. Each published result carries a label that says how it was produced:

| Label | Meaning |
| --- | --- |
| **Self-reported** | The submitter ran it and reported the scores. You reviewed it. |
| **Independently reproduced** | Another project reran the configuration on the same release and track. |
| **Plural-executed** | The Trials ran where Plural can vouch for them. No new Job earns this label yet. |

A label says how a result was produced. It doesn't say whether the Benchmark is a good
one. Every Job runs from the machine of whoever started it, so new results, your own
included, are self-reported for now.

The public manifest and its guarantees are specified in
[Benchmark publications](../architecture/benchmark-publications.md).
