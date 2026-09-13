---
route: /docs/reference/cli-commands
title: "Generated CLI command reference"
order: 210
description: "Generated reference for every Plural CLI command and option exposed by the Typer application."
audience: all
nav: true
nav_group: Reference
---

# Generated CLI command reference

This file is generated from the Typer application. Do not edit it by hand.
Run `uv run python scripts/generate_cli_reference.py` after changing the CLI.

## `plural`

```text

 Usage: plural [OPTIONS] COMMAND [ARGS]...

 Define environments, evaluate agents, and inspect reproducible results.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --install-completion          Install completion for the current shell.                          │
│ --show-completion             Show completion for the current shell, to copy it or customize the │
│                               installation.                                                      │
│ --help                        Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init        Create a small Python-first evaluation project.                                      │
│ validate    Load and validate any Python or YAML project object.                                 │
│ inspect     Show the fully resolved public object graph.                                         │
│ export      Export the resolved graph as canonical public YAML.                                  │
│ run         Run locally by default; use --hosted for explicit remote submission.                 │
│ schemas     Generate schemas from the public SDK models.                                         │
│ models      List and inspect the effective model catalog.                                        │
│ benchmarks  Inspect, compare, and export Benchmarks.                                             │
│ auth        Authenticate with hosted Plural services.                                            │
│ job         Advanced durable Job and event commands.                                             │
│ trial       Inspect and watch Trials.                                                            │
│ review      Inspect and submit human reviews.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural auth`

```text

 Usage: plural auth [OPTIONS] COMMAND [ARGS]...

 Authenticate with hosted Plural services.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ login   Authenticate using the hosted device flow.                                               │
│ logout  Remove stored credentials for the active profile.                                        │
│ status  Show local authentication context without exposing secrets.                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural auth login`

```text

 Usage: plural auth login [OPTIONS]

 Authenticate using the hosted device flow.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --no-browser                                                                                     │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural auth logout`

```text

 Usage: plural auth logout [OPTIONS]

 Remove stored credentials for the active profile.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural auth status`

```text

 Usage: plural auth status [OPTIONS]

 Show local authentication context without exposing secrets.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmarks`

```text

 Usage: plural benchmarks [OPTIONS] COMMAND [ARGS]...

 Inspect, compare, and export Benchmarks.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ show    Show one resolved Benchmark.                                                             │
│ diff    Compare two resolved Benchmark versions.                                                 │
│ export  Write a Benchmark and its pinned dependency graph.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmarks diff`

```text

 Usage: plural benchmarks diff [OPTIONS] {before} {after}

 Compare two resolved Benchmark versions.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    before      <str>  [required]                                                               │
│ *    after       <str>  [required]                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --catalog        <path>                                                                          │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmarks export`

```text

 Usage: plural benchmarks export [OPTIONS] {REF}

 Write a Benchmark and its pinned dependency graph.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    REF      <str>  [required]                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --output   -o      <path>  [required]                                                         │
│    --catalog          <path>                                                                     │
│    --help                     Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmarks show`

```text

 Usage: plural benchmarks show [OPTIONS] {REF}

 Show one resolved Benchmark.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    REF      <str>  [required]                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --catalog        <path>                                                                          │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural export`

```text

 Usage: plural export [OPTIONS] {REF}

 Export the resolved graph as canonical public YAML.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    REF      <str>  [required]                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --output   -o      <path>  [required]                                                         │
│    --catalog          <path>                                                                     │
│    --help                     Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural init`

```text

 Usage: plural init [OPTIONS] [path]

 Create a small Python-first evaluation project.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  Project directory. [default: .]                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --force                                                                                          │
│ --help           Show this message and exit.                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural inspect`

```text

 Usage: plural inspect [OPTIONS] {REF}

 Show the fully resolved public object graph.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    REF      <str>  [required]                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --catalog        <path>                                                                          │
│ --format         <json|yaml>  [default: yaml]                                                    │
│ --help                        Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural job`

```text

 Usage: plural job [OPTIONS] COMMAND [ARGS]...

 Advanced durable Job and event commands.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init    Create a path-based Job.                                                                 │
│ list    List durable local Jobs.                                                                 │
│ show    Show a Job, lock, result, and latest event.                                              │
│ submit  Submit a hosted Job from exact revision IDs.                                             │
│ watch   Replay or follow local or hosted append-only Job events.                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural job init`

```text

 Usage: plural job init [OPTIONS] [path]

 Create a path-based Job.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: job.yaml]                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --source               <path>            [required]                                           │
│    --source-kind          <benchmark|task>  [default: benchmark]                                 │
│ *  --agent        -a      <path>            [required]                                           │
│    --force                                                                                       │
│    --help                                   Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural job list`

```text

 Usage: plural job list [OPTIONS]

 List durable local Jobs.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --store        <path>  [default: .plural/jobs]                                                   │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural job show`

```text

 Usage: plural job show [OPTIONS] {job_id}

 Show a Job, lock, result, and latest event.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  [required]                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --store        <path>  [default: .plural/jobs]                                                   │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural job submit`

```text

 Usage: plural job submit [OPTIONS] [path]

 Submit a hosted Job from exact revision IDs.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: job.yaml]                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --source-revision-id        <str>  [required]                                                 │
│ *  --agent-revision-id         <str>  [required]                                                 │
│ *  --idempotency-key           <str>  [required]                                                 │
│    --name                      <str>  [default: Job]                                             │
│    --help                             Show this message and exit.                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural job watch`

```text

 Usage: plural job watch [OPTIONS] {job_id}

 Replay or follow local or hosted append-only Job events.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  [required]                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --store         <path>              [default: .plural/jobs]                                      │
│ --after         <int range> [x>=0]  [default: 0]                                                 │
│ --follow                                                                                         │
│ --json                                                                                           │
│ --hosted                                                                                         │
│ --help                              Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural models`

```text

 Usage: plural models [OPTIONS] COMMAND [ARGS]...

 List and inspect the effective model catalog.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list  List models in the effective bundled plus project catalog.                                 │
│ show  Show one effective catalog model.                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural models list`

```text

 Usage: plural models list [OPTIONS]

 List models in the effective bundled plus project catalog.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --catalog        <path>                                                                          │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural models show`

```text

 Usage: plural models show [OPTIONS] {model_id}

 Show one effective catalog model.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    model_id      <str>  [required]                                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --catalog        <path>                                                                          │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural review`

```text

 Usage: plural review [OPTIONS] COMMAND [ARGS]...

 Inspect and submit human reviews.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list           List local Trials awaiting human review.                                          │
│ submit         Durably append a local human-review submission.                                   │
│ hosted-list    List hosted human review assignments.                                             │
│ hosted-submit  Submit hosted human-review criterion scores.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural review hosted-list`

```text

 Usage: plural review hosted-list [OPTIONS]

 List hosted human review assignments.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --status        <str>  [default: awaiting_review]                                                │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural review hosted-submit`

```text

 Usage: plural review hosted-submit [OPTIONS] {assignment_id}

 Submit hosted human-review criterion scores.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    assignment_id      <str>  [required]                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --score                  <str>  criterion=value [required]                                    │
│ *  --idempotency-key        <str>  [required]                                                    │
│    --feedback               <str>                                                                │
│    --help                          Show this message and exit.                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural review list`

```text

 Usage: plural review list [OPTIONS] {job_id}

 List local Trials awaiting human review.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  [required]                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --store        <path>  [default: .plural/jobs]                                                   │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural review submit`

```text

 Usage: plural review submit [OPTIONS] {job_id} {trial_id}

 Durably append a local human-review submission.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    job_id        <str>  [required]                                                             │
│ *    trial_id      <str>  [required]                                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --verifier        <str>    [required]                                                         │
│ *  --score           <float>  [required]                                                         │
│    --feedback        <str>                                                                       │
│    --store           <path>   [default: .plural/jobs]                                            │
│    --help                     Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural run`

```text

 Usage: plural run [OPTIONS] {REF}

 Run locally by default; use --hosted for explicit remote submission.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    REF      <str>  Task, Benchmark, or Job reference. [required]                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --agent                    -a                <str>               Agent reference; repeatable.    │
│ --mode                                       <eval|train>                                        │
│ --attempts                                   <int range> [x>=1]                                  │
│ --concurrency                                <int range> [x>=1]                                  │
│ --per-runtime-concurrency                    <int range> [x>=1]                                  │
│ --dry-run                                                                                        │
│ --hosted                                                         Explicitly synchronize and      │
│                                                                  submit to hosted Plural.        │
│ --watch                        --no-watch                        Follow hosted Job events after  │
│                                                                  explicit submission.            │
│                                                                  [default: watch]                │
│ --json                                                           Render watched hosted events as │
│                                                                  JSON Lines.                     │
│ --idempotency-key                            <str>                                               │
│ --name                                       <str>               [default: Job]                  │
│ --format                                     <json|yaml>         [default: json]                 │
│ --catalog                                    <path>                                              │
│ --help                                                           Show this message and exit.     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural schemas`

```text

 Usage: plural schemas [OPTIONS] [path]

 Generate schemas from the public SDK models.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: schemas]                                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural trial`

```text

 Usage: plural trial [OPTIONS] COMMAND [ARGS]...

 Inspect and watch Trials.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list   List planned Trials and current states.                                                   │
│ watch  Replay or follow events for one Trial.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural trial list`

```text

 Usage: plural trial list [OPTIONS] {job_id}

 List planned Trials and current states.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  [required]                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --store        <path>  [default: .plural/jobs]                                                   │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural trial watch`

```text

 Usage: plural trial watch [OPTIONS] {trial_id}

 Replay or follow events for one Trial.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    trial_id      <str>  [required]                                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --job           <str>               [required]                                                │
│    --store         <path>              [default: .plural/jobs]                                   │
│    --after         <int range> [x>=0]  [default: 0]                                              │
│    --follow                                                                                      │
│    --json                                                                                        │
│    --hosted                                                                                      │
│    --help                              Show this message and exit.                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural validate`

```text

 Usage: plural validate [OPTIONS] {REF}

 Load and validate any Python or YAML project object.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    REF      <str>  [required]                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --catalog        <path>                                                                          │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```
