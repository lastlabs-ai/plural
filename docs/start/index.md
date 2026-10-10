---
route: /docs/start
title: Start here
order: 21
description: "Pick the path that matches what you have today: traces from an agent you already run, a system your work happens in, or nothing yet. Each one ends at a Benchmark you can rerun."
audience: all
nav: true
nav_group: Start
---
# Start here

What do you have today? Pick the path that matches it.

- **[Traces from an agent you already run.](from-traces.md)** Score the conversations
  your agent already had, then turn them into Tasks you can run any model on.
- **[A system your work happens in](from-a-system.md)**, such as Salesforce, an MCP
  server, an API, or a database. Connect it as an App, write a Rewarder that checks
  the system itself, and run models against it.
- **[Nothing yet.](from-scratch.md)** Build a small game like Wordle from an empty
  folder to a scored run, in about fifteen minutes.

All three paths end in the same place: a **Benchmark**, a set of Tasks you can rerun
on any model and compare. They differ only in where the Environment comes from.

| You start with | Plural drafts | You write |
| --- | --- | --- |
| Traces | A replay App, one Task per trace, a model-judge Rewarder, a Benchmark | Sharper instructions and criteria |
| A system | An App with the system's actions | Tasks, and a Rewarder that queries the system |
| Nothing | Templates marked `PLURAL-TODO` | The App, Tasks, and Rewarder |

Each page assumes you have installed Plural and signed in. If you haven't, do the
first three sections of [Getting started](../getting-started.md) first: create an
account, install, and sign in. If words like App, Task, and Rewarder are new, read
[Core concepts](../getting-started/concepts.md); it takes about five minutes.
