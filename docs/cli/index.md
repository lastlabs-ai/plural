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
plural env init NAME [--python] [--bare]
plural task init NAME [--environment ENV] [--verifier NAME]
plural agent init NAME --model MODEL [--harness HARNESS]
plural verifier|harness|benchmark init NAME
plural env|task|verifier|harness|agent|benchmark validate|show|push|pull [NAME]
plural env|task|verifier|harness|agent|benchmark list
plural env|task|verifier|harness|agent|benchmark delete NAME [--hosted] [-y]
plural benchmark add|remove TASK [--benchmark NAME]
plural app add ENV (--mcp URL_OR_COMMAND | --openapi SPEC | --traces FILE | --files-server)
           [--app APP] [--header K=V] [--server-env K=V] [--tool NAME] [--operation ID]
           [--credential NAME] [--copy]
plural app list ENV
plural app remove ENV APP
plural env serve NAME [--app APP] [--port 3825]
plural run (-t TASK | -b BENCHMARK) (-m MODEL [--harness HARNESS] | -a AGENT)
           [--record] [--evaluation-track ID] [--attempts N] [--concurrency N]
           [--plural-version VERSION] [--dry-run] [--json]
plural job list
plural job show|rerun|record JOB_ID
plural trial show|rerun TRIAL_ID
plural review list
plural review submit TRIAL_ID --verifier NAME --score SCORE
plural verifier try|apply NAME (--trial TRIAL_ID... | --job JOB_ID)
plural reward show TRIAL_ID
plural reward export (--trial TRIAL_ID... | --job JOB_ID) [--verifier NAME[@VERSION]]
plural model list
plural secret list|set|delete
plural credential list|set|delete
plural auth login|logout|status
plural auth scope [--account | --project NAME] [--org ORG]
plural session export|import
```

Arguments in brackets are optional. A resource name you leave out defaults to the
resource folder you are in, and `benchmark add` and `benchmark remove` default to the
Benchmark folder you are in. Where a command takes NAME[@REF], REF is a revision
number (@3), a release version (@1.0.0), or a content hash; `pull`, `show`, and `run`
accept it.

`delete` removes the resource's folder and refuses while another resource in the
project uses it. Add `--hosted` to delete it from the hosted project too; Jobs and
Trials that pinned its revisions can still read them. Resources are not renamed in
place: create the new one, point its users at it, and delete the old one.

## Where runs happen

- **Locally (the default).** Every run is a new Job, recorded under `.plural/jobs/`
  in your project.
- **Locally, and recorded in your hosted project.** `plural run ... --record` runs on
  your machine and records the Job in your private hosted project as it goes.
  `plural job record JOB_ID` does the same for a local Job that has already finished.
- **In cloud sandboxes.** An Environment whose `runtime` is a cloud provider, such as
  `daytona`, runs each Trial in a remote sandbox. The Job still runs from your machine,
  with or without `--record`.

`--record` pushes any input your hosted project does not have yet before the run
starts. Plural never runs a Job on its own servers.

`-m` without `--harness` uses `native`, Plural's built-in tool loop, as the **Harness** (the
loop that decides what the model does next).

The [CLI guide](evaluation.md) walks through these commands and ends with the
generated reference for every option. Projects from Plural 0.14 or earlier use a
different layout; see [Migrate to 0.15](../migration/projects.md).
