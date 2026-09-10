---
route: /docs/reference/cli-commands
title: "Generated CLI command reference"
order: 510
description: "Generated reference for every Plural CLI command and option exposed by the Typer application."
audience: all
---

# Generated CLI command reference

This file is generated from the Typer application. Do not edit it by hand.
Run `uv run python scripts/generate_cli_reference.py` after changing the CLI.

## `plural`

```text

 Usage: plural [OPTIONS] COMMAND [ARGS]...

 Author and run schema-v2 Plural revision graphs.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --install-completion          Install completion for the current shell.                          │
│ --show-completion             Show completion for the current shell, to copy it or customize the │
│                               installation.                                                      │
│ --help                        Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ run        Synchronize and run a hosted Job, or execute explicitly offline.                      │
│ schemas    Generate canonical schema-v2 references.                                              │
│ env        Manage Environment revisions.                                                         │
│ task       Manage Task revisions.                                                                │
│ verifier   Manage Verifier revisions.                                                            │
│ agent      Manage Environment-independent Agent revisions.                                       │
│ harness    Manage Harness revisions.                                                             │
│ benchmark  Manage cross-Environment Benchmarks.                                                  │
│ job        Manage durable Jobs and event streams.                                                │
│ trial      Inspect and watch Trials.                                                             │
│ review     Inspect and submit human reviews.                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural agent`

```text

 Usage: plural agent [OPTIONS] COMMAND [ARGS]...

 Manage Environment-independent Agent revisions.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create an Agent independent of Environment identity.                                   │
│ validate  Validate an Agent.                                                                     │
│ show      Show an Agent.                                                                         │
│ push      Publish an AgentDefinition parent and immutable revision.                              │
│ publish   Publish an existing hosted Agent revision.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural agent init`

```text

 Usage: plural agent init [OPTIONS] [path]

 Create an Agent independent of Environment identity.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: agent.yaml]                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│    --name           <str>   [default: agent]                                                     │
│ *  --model          <str>   [required]                                                           │
│    --harness        <path>                                                                       │
│    --force                                                                                       │
│    --help                   Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural agent publish`

```text

 Usage: plural agent publish [OPTIONS] {resource_id} {revision_id}

 Publish an existing hosted Agent revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    resource_id      <str>  [required]                                                          │
│ *    revision_id      <str>  [required]                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural agent push`

```text

 Usage: plural agent push [OPTIONS] [path]

 Publish an AgentDefinition parent and immutable revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: agent.yaml]                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --harness-revision-id        <str>                                                               │
│ --help                              Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural agent show`

```text

 Usage: plural agent show [OPTIONS] [path]

 Show an Agent.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: agent.yaml]                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural agent validate`

```text

 Usage: plural agent validate [OPTIONS] [path]

 Validate an Agent.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: agent.yaml]                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmark`

```text

 Usage: plural benchmark [OPTIONS] COMMAND [ARGS]...

 Manage cross-Environment Benchmarks.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a Benchmark selecting Task revisions across Environments.                       │
│ validate  Validate a complete Benchmark revision graph.                                          │
│ show      Show a resolved Benchmark.                                                             │
│ push      Publish a cross-Environment Benchmark revision.                                        │
│ publish   Publish an existing hosted Benchmark revision.                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmark init`

```text

 Usage: plural benchmark init [OPTIONS] [path]

 Create a Benchmark selecting Task revisions across Environments.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: benchmark.yaml]                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│    --name           <str>   [default: benchmark]                                                 │
│ *  --task   -t      <path>  [required]                                                           │
│    --force                                                                                       │
│    --help                   Show this message and exit.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmark publish`

```text

 Usage: plural benchmark publish [OPTIONS] {resource_id} {revision_id}

 Publish an existing hosted Benchmark revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    resource_id      <str>  [required]                                                          │
│ *    revision_id      <str>  [required]                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmark push`

```text

 Usage: plural benchmark push [OPTIONS] [path]

 Publish a cross-Environment Benchmark revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: benchmark.yaml]                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --task-revision-id        <str>  [required]                                                   │
│    --help                           Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmark show`

```text

 Usage: plural benchmark show [OPTIONS] [path]

 Show a resolved Benchmark.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: benchmark.yaml]                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural benchmark validate`

```text

 Usage: plural benchmark validate [OPTIONS] [path]

 Validate a complete Benchmark revision graph.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: benchmark.yaml]                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural env`

```text

 Usage: plural env [OPTIONS] COMMAND [ARGS]...

 Manage Environment revisions.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a standalone Environment package.                                               │
│ validate  Validate a canonical Environment.                                                      │
│ show      Show a canonical Environment.                                                          │
│ push      Publish an Environment parent and immutable revision.                                  │
│ publish   Publish an existing hosted Environment revision.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural env init`

```text

 Usage: plural env init [OPTIONS] [path]

 Create a standalone Environment package.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --name         <str>  [default: environment]                                                     │
│ --force                                                                                          │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural env publish`

```text

 Usage: plural env publish [OPTIONS] {resource_id} {revision_id}

 Publish an existing hosted Environment revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    resource_id      <str>  [required]                                                          │
│ *    revision_id      <str>  [required]                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural env push`

```text

 Usage: plural env push [OPTIONS] [path]

 Publish an Environment parent and immutable revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural env show`

```text

 Usage: plural env show [OPTIONS] [path]

 Show a canonical Environment.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural env validate`

```text

 Usage: plural env validate [OPTIONS] [path]

 Validate a canonical Environment.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness`

```text

 Usage: plural harness [OPTIONS] COMMAND [ARGS]...

 Manage Harness revisions.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a Harness package.                                                              │
│ validate  Validate and lock a Harness.                                                           │
│ show      Show a Harness.                                                                        │
│ push      Publish a Harness parent and immutable revision.                                       │
│ publish   Publish an existing hosted Harness revision.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness init`

```text

 Usage: plural harness init [OPTIONS] [path]

 Create a Harness package.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --name         <str>  [default: harness]                                                         │
│ --force                                                                                          │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness publish`

```text

 Usage: plural harness publish [OPTIONS] {resource_id} {revision_id}

 Publish an existing hosted Harness revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    resource_id      <str>  [required]                                                          │
│ *    revision_id      <str>  [required]                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness push`

```text

 Usage: plural harness push [OPTIONS] [path]

 Publish a Harness parent and immutable revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness show`

```text

 Usage: plural harness show [OPTIONS] [path]

 Show a Harness.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural harness validate`

```text

 Usage: plural harness validate [OPTIONS] [path]

 Validate and lock a Harness.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural job`

```text

 Usage: plural job [OPTIONS] COMMAND [ARGS]...

 Manage durable Jobs and event streams.

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

 Usage: plural run [OPTIONS] {source}

 Synchronize and run a hosted Job, or execute explicitly offline.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    source      <path>  Task, Benchmark, or Job YAML. [required]                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --agent                    -a                <path>                                              │
│ --mode                                       <eval|train>                                        │
│ --attempts                                   <int range> [x>=1]                                  │
│ --concurrency                                <int range> [x>=1]                                  │
│ --per-runtime-concurrency                    <int range> [x>=1]                                  │
│ --dry-run                                                                                        │
│ --offline,--private                                              Keep execution and its durable  │
│                                                                  log local.                      │
│ --watch                        --no-watch                        Follow hosted Job events after  │
│                                                                  submission.                     │
│                                                                  [default: watch]                │
│ --json                                                           Render watched hosted events as │
│                                                                  JSON Lines.                     │
│ --idempotency-key                            <str>                                               │
│ --name                                       <str>               [default: Job]                  │
│ --format                                     <json|yaml>         [default: json]                 │
│ --help                                                           Show this message and exit.     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural schemas`

```text

 Usage: plural schemas [OPTIONS] [path]

 Generate canonical schema-v2 references.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: schemas]                                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural task`

```text

 Usage: plural task [OPTIONS] COMMAND [ARGS]...

 Manage Task revisions.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a Task pinned to an Environment and Verifiers.                                  │
│ validate  Validate a complete Task revision graph.                                               │
│ show      Show a resolved Task.                                                                  │
│ push      Publish a Task revision with exact hosted dependencies.                                │
│ publish   Publish an existing hosted Task revision.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural task init`

```text

 Usage: plural task init [OPTIONS] [path]

 Create a Task pinned to an Environment and Verifiers.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: task.yaml]                                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│    --id                   <str>   [default: task]                                                │
│ *  --environment  -e      <path>  [required]                                                     │
│ *  --verifier     -v      <path>  [required]                                                     │
│    --force                                                                                       │
│    --help                         Show this message and exit.                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural task publish`

```text

 Usage: plural task publish [OPTIONS] {resource_id} {revision_id}

 Publish an existing hosted Task revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    resource_id      <str>  [required]                                                          │
│ *    revision_id      <str>  [required]                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural task push`

```text

 Usage: plural task push [OPTIONS] [path]

 Publish a Task revision with exact hosted dependencies.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: task.yaml]                                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --environment-revision-id        <str>  [required]                                            │
│ *  --verifier-revision-id           <str>  [required]                                            │
│    --help                                  Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural task show`

```text

 Usage: plural task show [OPTIONS] [path]

 Show a resolved Task.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: task.yaml]                                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural task validate`

```text

 Usage: plural task validate [OPTIONS] [path]

 Validate a complete Task revision graph.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: task.yaml]                                                         │
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

## `plural verifier`

```text

 Usage: plural verifier [OPTIONS] COMMAND [ARGS]...

 Manage Verifier revisions.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a deterministic, agent, or human Verifier.                                      │
│ validate  Validate a Verifier.                                                                   │
│ show      Show a Verifier.                                                                       │
│ push      Publish a Verifier parent and immutable revision.                                      │
│ publish   Publish an existing hosted Verifier revision.                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural verifier init`

```text

 Usage: plural verifier init [OPTIONS] [path]

 Create a deterministic, agent, or human Verifier.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: verifier.yaml]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --name         <str>                        [default: verifier]                                  │
│ --kind         <deterministic|agent|human>  [default: deterministic]                             │
│ --force                                                                                          │
│ --help                                      Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural verifier publish`

```text

 Usage: plural verifier publish [OPTIONS] {resource_id} {revision_id}

 Publish an existing hosted Verifier revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    resource_id      <str>  [required]                                                          │
│ *    revision_id      <str>  [required]                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural verifier push`

```text

 Usage: plural verifier push [OPTIONS] [path]

 Publish a Verifier parent and immutable revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: verifier.yaml]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural verifier show`

```text

 Usage: plural verifier show [OPTIONS] [path]

 Show a Verifier.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: verifier.yaml]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## `plural verifier validate`

```text

 Usage: plural verifier validate [OPTIONS] [path]

 Validate a Verifier.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: verifier.yaml]                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```
