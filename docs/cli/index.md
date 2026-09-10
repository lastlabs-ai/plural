---
route: /docs/cli
title: "Command-line interface"
order: 110
description: "The schema-v2 CLI authors and runs the same canonical revision graph as the Python SDK."
audience: all
---
# Command-line interface

The schema-v2 CLI authors and runs the same canonical revision graph as the
Python SDK.

```bash
pip install plural
plural --help
```

## Author revisions

Create each independently, then connect them through explicit paths:

```bash
plural env init environment --name support
plural verifier init verifier.yaml --name correct --kind deterministic
plural task init task.yaml --id support-1 \
  --environment environment --verifier verifier.yaml
plural harness init harness --name support-loop
plural agent init agent.yaml --name candidate \
  --model openai/gpt-4.1-mini --harness harness
plural benchmark init benchmark.yaml --name support-suite --task task.yaml
plural job init job.yaml --source benchmark.yaml \
  --source-kind benchmark --agent agent.yaml
```

Environment owns runtime placement, network, resources, secrets, actions,
typed state/observation, and train-only Rewarders. Task owns its instructions,
info, and exact Environment and weighted Verifier revisions. Agent is
Environment-independent. A Benchmark can select Tasks from multiple
Environments.

## Run

`plural run` accepts a Task, Benchmark, or Job. A normal authenticated run
validates the entire graph, synchronizes and publishes every canonical
revision in dependency order, submits the Job with the exact returned revision
IDs, prints it, and follows its hosted event stream:

```bash
plural run task.yaml --agent agent.yaml --mode eval --dry-run
plural run benchmark.yaml --agent agent.yaml --mode train --attempts 2
plural run job.yaml --concurrency 8 --per-runtime-concurrency 2 --json
```

Shared Harnesses, Environments, Verifiers, and Tasks are uploaded once and
reused. The default idempotency key is the stable local Job ID; pass
`--idempotency-key RELEASE_KEY` to choose one. Use `--no-watch` to return after
submission.

To keep execution and its durable log on the current machine, opt in
explicitly:

```bash
plural run job.yaml --offline
plural run job.yaml --private
```

`--private` is equivalent to `--offline`.

Eval disables Rewarders and TITO capture but still runs final Verifiers. Train
enables Rewarders and fails preflight unless the Harness supports exact TITO
capture. TITO content is stored as immutable hashed artifacts.

## Observe and review

Jobs append monotonic durable events. Replay them for automation or follow them
live:

```bash
plural job list
plural job show JOB_ID
plural job watch JOB_ID --json
plural job watch JOB_ID --after 42 --follow
plural job watch JOB_ID --hosted --json
plural trial list JOB_ID
plural trial watch TRIAL_ID --job JOB_ID --json --follow
plural review list JOB_ID
plural review submit JOB_ID TRIAL_ID \
  --verifier human-review --score 1 --feedback approved
```

A Trial is one Agent × Task × attempt slot. Retries are separate
TrialExecutions under the same Trial. Human Verifiers leave the Trial in
`awaiting_review` until review is submitted.

`plural job submit` is the advanced hosted workflow when every source and Agent
revision ID is already known. Unlike `plural run`, it does not synchronize the
graph.

Most commands emit deterministic JSON; `run` also supports
`--format json|yaml`. The generated [command reference](../reference/cli-commands.md)
is the exact authority for arguments and options.
