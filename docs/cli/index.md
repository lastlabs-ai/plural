---
route: /docs/cli
title: "Command-line interface"
order: 110
description: "Create a project, push and pull its resources, run Tasks and Benchmarks, and inspect the resulting Jobs."
audience: all
nav: false
---
# Command-line interface

The CLI works on a project: a `project.yaml` file with one directory per resource
beside it. Resource commands name a resource by its directory name.

```text
plural project init NAME [--push]
plural project show NAME
plural env|task|verifier|harness|agent|benchmark init NAME
plural env|task|verifier|harness|agent|benchmark validate|show|push|pull [NAME]
plural env|task|verifier|harness|agent|benchmark list
plural benchmark add|remove TASK [--benchmark NAME]
plural run (-t TASK | -b BENCHMARK) (-m MODEL [-h HARNESS] | -a AGENT)
           [--hosted] [--follow] [--attempts N] [--concurrency N] [--dry-run] [--json]
plural job list
plural job show|rerun JOB_ID
plural trial show|rerun TRIAL_ID
plural review list
plural review submit TRIAL_ID --verifier NAME --score SCORE
plural models list
plural auth login|logout|status|scope
plural session export|import
```

Arguments in brackets are optional. A resource name you omit defaults to the resource
directory you are in, and `benchmark add` and `benchmark remove` default to the
Benchmark directory you are in.

Runs are local by default, and every run is a new Job recorded under
`.plural/jobs/`. `plural run ... --hosted` runs on hosted infrastructure using
revisions you have already pushed, and needs `plural auth login`. `-m` without `-h`
uses `native`, Plural's built-in tool loop.

The [CLI guide](evaluation.md) walks through these commands and ends with the
generated reference for every option. Projects from Plural 0.14 or earlier use a
different layout; see [Migrate to 0.15](../migration/projects.md).
