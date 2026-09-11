---
route: /docs/running/traces
title: "Traces"
order: 90
description: "A Trace is the episode. Public observations stay public. Hidden state stays hidden. Open one from the CLI or Plural Intel."
audience: all
nav: true
nav_group: Running
outcome: You know what a Trace contains and where hidden state does not go.
---
# Traces

A Trace is what happened. Turns, actions, observations, Verifier results, artifact pointers. It is pinned to the exact Environment, Task, Agent, and Verifier revisions from the Trial.

```mermaid
flowchart LR
  t0[reset]
  t1[guess]
  t2[guess]
  obs[observation]
  hidden[hidden_state]
  t0 --> obs
  t1 --> obs
  t2 --> obs
  t0 --> hidden
```

Open a Trace from a local Job under `.plural/jobs`, or open the same Trial in Plural Intel. The board, the guess list, and the rendered text are public. The secret is not. Hidden state never enters `public_payload`. Verifiers that asked for it already received a filtered `environment_view`.

A dataset is an export of Traces or Tasks, not the starting object. Build the world first. Export when you want a frozen set for later training or a shareable eval slice.

What this unlocks: you can replay an episode without re-running the Agent, and you can teach a new Agent from traces you already trust. If a human still has to look, [Reviews](reviews.md) is the pause.
