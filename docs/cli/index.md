---
route: /docs/cli
title: "Command-line interface"
order: 110
description: "Create a project, push and pull its resources, run Tasks and Benchmarks, and inspect the resulting Jobs."
audience: all
nav: false
---
# Command-line interface

The `plural` command-line tool lets you do everything in Plural from a terminal:
set up a project, run models against your Tasks, and look at the results. It is a
good fit if you like working in a terminal, want to script your runs, or keep your
project in version control.

Every command works on a **project**: a folder with a `project.yaml` file and one
subfolder per resource, such as `environments/wordle/` or `tasks/crane/`. Commands
name a resource by its folder name. If you are new to words like Task, Agent, or
Benchmark, [Core concepts](../getting-started/concepts.md) explains them in five
minutes.

## The commands most people need

```bash
plural project init support-eval
plural run -t ticket-1 -m openai/gpt-5.6-luna
plural job list
plural job show JOB_ID
```

The first creates a project. The second runs one Task (one assignment) with one
model and records the result as a new **Job**. The last two list your Jobs and show
the scores and details of one of them.

Runs happen on your own machine by default. A run that calls a real model needs a
Plural API key, stored with `plural auth login --api-key-stdin` or set in
`PLURAL_API_KEY`.

## Every command at a glance

```text
plural project init NAME [--push]
plural project show NAME
plural project push
plural env|task|verifier|harness|agent|benchmark init NAME
plural env|task|verifier|harness|agent|benchmark validate|show|push|pull [NAME]
plural env|task|verifier|harness|agent|benchmark list
plural benchmark add|remove TASK [--benchmark NAME]
plural run (-t TASK | -b BENCHMARK) (-m MODEL [-h HARNESS] | -a AGENT)
           [--hosted [--follow] | --track] [--attempts N] [--concurrency N]
           [--plural-version VERSION] [--dry-run] [--json]
plural job list
plural job show|rerun|push JOB_ID
plural trial show|rerun TRIAL_ID
plural review list
plural review submit TRIAL_ID --verifier NAME --score SCORE
plural models list
plural auth login|logout|status|scope
plural session export|import
```

Arguments in brackets are optional. A resource name you leave out defaults to the
resource folder you are in, and `benchmark add` and `benchmark remove` default to the
Benchmark folder you are in.

## Where runs happen

- **Locally (the default).** Every run is a new Job, recorded under `.plural/jobs/`
  in your project.
- **Locally, and recorded in your hosted project.** `plural run ... --track` runs on
  your machine and records the Job in your private hosted project as it goes.
  `plural job push JOB_ID` does the same for a local Job that has already finished.
- **On Plural's hosted infrastructure.** `plural run ... --hosted` sends the run to
  Plural's workers and needs `plural auth login`. `--track` and `--hosted` push any
  input your hosted project does not have yet before the run starts.

`-m` without `-h` uses `native`, Plural's built-in tool loop, as the **Harness** (the
loop that decides what the model does next).

The [CLI guide](evaluation.md) walks through these commands and ends with the
generated reference for every option. Projects from Plural 0.14 or earlier use a
different layout; see [Migrate to 0.15](../migration/projects.md).
