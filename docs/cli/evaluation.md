---
route: /docs/cli/evaluation
title: CLI guide
order: 120
description: Validate, inspect, export, run, compare, watch, and review the same evaluation objects used by the Python SDK.
audience: all
nav: true
nav_group: Interfaces
---
# CLI guide

Use the CLI to validate a project, preview its Trials, run an evaluation, and inspect results. Commands accept YAML files or Python references such as `job.py:job`, which selects the `job` object in that file.

## Create and validate a project

```bash
plural init support-eval
cd support-eval
plural validate project.py:job
plural inspect project.py:job
plural export project.py:job --output job.yaml
plural run job.yaml --dry-run
```

A live run needs `plural auth login` or `--api-key`. Dry-run does not.

A new scaffold still needs executable Environment and Verifier
implementations. The [support queue tutorial](../tutorials/support-queue.md)
provides both before its first live run.

A Job contains Agents. To run a Task or Benchmark directly, add one or more
repeatable Agent references:

```bash
plural run benchmark.yaml \
  --agent agents/careful.yaml \
  --agent agents/concise.yaml \
  --attempts 2 \
  --concurrency 4 \
  --dry-run
```

CLI overrides apply only when supplied. Otherwise Python defaults remain:
`mode=eval`, `attempts=1`, `concurrency=1`, and
`per_runtime_concurrency=1`.

## Models and Benchmarks

```bash
plural models list
plural models show openai/gpt-5.6-luna
plural benchmarks show benchmark.yaml
plural benchmarks diff benchmark-v1.yaml benchmark-v2.yaml
plural benchmarks export benchmark.yaml --output benchmark-graph.yaml
```

Use `--catalog PATH` on commands that load model-backed objects when your
project registers additional catalog entries.

## Jobs, Trials, and reviews

```bash
plural job list
plural job show JOB_ID
plural job watch JOB_ID --follow
plural trial list JOB_ID
plural trial watch TRIAL_ID --job JOB_ID --follow
plural review list JOB_ID
plural review submit JOB_ID TRIAL_ID \
  --verifier policy-review \
  --score 2 \
  --feedback "Meets policy."
```

Local inspection commands default to `.plural/jobs`; use `--store PATH` when
the Job ran from another source directory.

## Local and hosted

`plural run` executes locally by default. This describes orchestration and
storage, not Runtime provider or network access. Use `--hosted` only when you
intend to sync and submit:

```bash
plural auth status
plural run job.yaml --hosted
```

`--offline` is a hidden compatibility alias and is unnecessary for the normal
local path.

## Command reference

<!-- generated-cli-reference -->
This section is generated from the Typer application. Run `uv run python scripts/generate_cli_reference.py` after changing the CLI.

### `plural`

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
│ env         Author, inspect, and publish Environments.                                           │
│ task        Author, inspect, and publish Tasks.                                                  │
│ verifier    Author, inspect, and publish Verifiers.                                              │
│ agent       Author, inspect, and publish Agents.                                                 │
│ benchmark   Author, inspect, and publish Benchmarks.                                             │
│ models      List and inspect the effective model catalog.                                        │
│ harness     List built-in Harnesses or author a custom one.                                      │
│ benchmarks  Inspect, compare, and export Benchmarks.                                             │
│ auth        Authenticate with hosted Plural services.                                            │
│ job         Advanced durable Job and event commands.                                             │
│ trial       Inspect and watch Trials.                                                            │
│ review      Inspect and submit human reviews.                                                    │
│ session     Export and redeploy portable agent sessions.                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent`

```text

 Usage: plural agent [OPTIONS] COMMAND [ARGS]...

 Author, inspect, and publish Agents.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create an Agent independent of Environment identity.                                   │
│ validate  Validate an Agent.                                                                     │
│ show      Show an Agent.                                                                         │
│ push      Publish an Agent parent and immutable revision.                                        │
│ publish   Publish an existing hosted Agent revision.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent init`

```text

 Usage: plural agent init [OPTIONS] [path]

 Create an Agent independent of Environment identity.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: agent.yaml]                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│    --name           <str>  [default: agent]                                                      │
│ *  --model          <str>  [required]                                                            │
│    --harness        <str>                                                                        │
│    --force                                                                                       │
│    --help                  Show this message and exit.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent publish`

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

### `plural agent push`

```text

 Usage: plural agent push [OPTIONS] [path]

 Publish an Agent parent and immutable revision.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: agent.yaml]                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --harness-revision-id        <str>                                                               │
│ --help                              Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural agent show`

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

### `plural agent validate`

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

### `plural auth`

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

### `plural auth login`

```text

 Usage: plural auth login [OPTIONS]

 Authenticate using the hosted device flow.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --no-browser                                                                                     │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural auth logout`

```text

 Usage: plural auth logout [OPTIONS]

 Remove stored credentials for the active profile.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural auth status`

```text

 Usage: plural auth status [OPTIONS]

 Show local authentication context without exposing secrets.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural benchmark`

```text

 Usage: plural benchmark [OPTIONS] COMMAND [ARGS]...

 Author, inspect, and publish Benchmarks.

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

### `plural benchmark init`

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

### `plural benchmark publish`

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

### `plural benchmark push`

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

### `plural benchmark show`

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

### `plural benchmark validate`

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

### `plural benchmarks`

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

### `plural benchmarks diff`

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

### `plural benchmarks export`

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

### `plural benchmarks show`

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

### `plural env`

```text

 Usage: plural env [OPTIONS] COMMAND [ARGS]...

 Author, inspect, and publish Environments.

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

### `plural env init`

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

### `plural env publish`

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

### `plural env push`

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

### `plural env show`

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

### `plural env validate`

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

### `plural export`

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

### `plural harness`

```text

 Usage: plural harness [OPTIONS] COMMAND [ARGS]...

 List built-in Harnesses or author a custom one.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ list      List built-in Harnesses that Agents can attach by name.                                │
│ schema    Show the accepted kwargs schema for a built-in Harness.                                │
│ init      Create a custom Harness.                                                               │
│ validate  Validate and lock a Harness.                                                           │
│ show      Show a Harness.                                                                        │
│ push      Publish a Harness parent and immutable revision.                                       │
│ publish   Publish an existing hosted Harness revision.                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness init`

```text

 Usage: plural harness init [OPTIONS] [path]

 Create a custom Harness.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  [default: .]                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --name         <str>  [default: harness]                                                         │
│ --force                                                                                          │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness list`

```text

 Usage: plural harness list [OPTIONS]

 List built-in Harnesses that Agents can attach by name.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness publish`

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

### `plural harness push`

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

### `plural harness schema`

```text

 Usage: plural harness schema [OPTIONS] {name}

 Show the accepted kwargs schema for a built-in Harness.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Built-in Harness name. [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural harness show`

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

### `plural harness validate`

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

### `plural init`

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

### `plural inspect`

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

### `plural job`

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

### `plural job init`

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

### `plural job list`

```text

 Usage: plural job list [OPTIONS]

 List durable local Jobs.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --store        <path>  [default: .plural/jobs]                                                   │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural job show`

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

### `plural job submit`

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

### `plural job watch`

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

### `plural models`

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

### `plural models list`

```text

 Usage: plural models list [OPTIONS]

 List models in the effective bundled plus project catalog.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --catalog        <path>                                                                          │
│ --help                   Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural models show`

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

### `plural review`

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

### `plural review hosted-list`

```text

 Usage: plural review hosted-list [OPTIONS]

 List hosted human review assignments.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --status        <str>  [default: awaiting_review]                                                │
│ --help                 Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural review hosted-submit`

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

### `plural review list`

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

### `plural review submit`

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

### `plural run`

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
│ --api-key                                    <str>               Bring-your-own                  │
│                                                                  OpenAI-compatible key.          │
│ --name                                       <str>               [default: Job]                  │
│ --format                                     <json|yaml>         [default: json]                 │
│ --catalog                                    <path>                                              │
│ --help                                                           Show this message and exit.     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural schemas`

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

### `plural session`

```text

 Usage: plural session [OPTIONS] COMMAND [ARGS]...

 Export and redeploy portable agent sessions.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ export  Export a session bundle from a hosted trial or local files.                              │
│ import  Redeploy a bundle as a separate instance directory.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural session export`

```text

 Usage: plural session export [OPTIONS]

 Export a session bundle from a hosted trial or local files.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --trial              <str>   Hosted trial id.                                                    │
│ --agent              <path>  Agent YAML or JSON file.                                            │
│ --environment        <path>  Environment YAML or JSON file.                                      │
│ --state              <path>  State JSON file.                                                    │
│ --data               <str>   Data reference to record.                                           │
│ --data-dir           <path>  Directory bundled into data/.                                       │
│ --name               <str>   Snapshot name.                                                      │
│ --out                <path>  Bundle directory. [default: sessions]                               │
│ --help                       Show this message and exit.                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural session import`

```text

 Usage: plural session import [OPTIONS] {bundle}

 Redeploy a bundle as a separate instance directory.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    bundle      <path>  Session bundle directory. [required]                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --dest        <path>  Parent directory for the new instance.                                     │
│ --help                Show this message and exit.                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task`

```text

 Usage: plural task [OPTIONS] COMMAND [ARGS]...

 Author, inspect, and publish Tasks.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create a local Task directory without publishing it.                                   │
│ validate  Validate a complete Task revision graph.                                               │
│ show      Show a resolved Task.                                                                  │
│ push      Publish a Task revision, resolving hosted environment and verifier slugs.              │
│ publish   Publish an existing hosted Task revision.                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task init`

```text

 Usage: plural task init [OPTIONS] {name}

 Create a local Task directory without publishing it.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      <str>  Task slug and local directory name. [required]                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --environment  -e      <str>  Hosted environment slug/id or local file.                          │
│ --verifier     -v      <str>  Hosted verifier slug/id or local file.                             │
│ --bare                        Create an empty task package.                                      │
│ --push                        Publish the new task immediately.                                  │
│ --force                       Replace existing task files.                                       │
│ --help                        Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task publish`

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

### `plural task push`

```text

 Usage: plural task push [OPTIONS] [path]

 Publish a Task revision, resolving hosted environment and verifier slugs.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────╮
│   path      <path>  Task file or task directory. [default: task.yaml]                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────╮
│ --environment-revision-id        <str>  Override the hosted environment revision.                │
│ --verifier-revision-id           <str>  Override a hosted verifier revision.                     │
│ --help                                  Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

### `plural task show`

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

### `plural task validate`

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

### `plural trial`

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

### `plural trial list`

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

### `plural trial watch`

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

### `plural validate`

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

### `plural verifier`

```text

 Usage: plural verifier [OPTIONS] COMMAND [ARGS]...

 Author, inspect, and publish Verifiers.

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

### `plural verifier init`

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

### `plural verifier publish`

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

### `plural verifier push`

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

### `plural verifier show`

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

### `plural verifier validate`

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
<!-- /generated-cli-reference -->
