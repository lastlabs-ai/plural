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

The CLI resolves Python and YAML through the same loader as the SDK. `REF` can
be a YAML path or `path.py:object`.

## Golden flow

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

The [generated command reference](../reference/cli-commands.md) is the source
for every argument, default, and option.
