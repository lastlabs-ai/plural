---
route: /docs/tutorials/cli-walkthrough
title: "Run your first schema-v2 Job"
order: 50
description: "This walkthrough creates a complete revision graph, runs it through the hosted service by default, and shows the explicit offline alternative."
audience: all
---
# Run your first schema-v2 Job

This walkthrough creates a complete revision graph. Dry runs make no hosted
writes. A normal authenticated run publishes the graph and submits a hosted
Job; `--offline` or `--private` keeps execution and durable state local.

## 1. Create the Environment

```bash
plural env init environment --name support
```

Edit `environment/environment.yaml` to define instructions, actions, typed
state/observation, resources, secrets, and runtime. Runtime provider, placement,
network, and compute belong here—not on the Job.

## 2. Create a Verifier and Task

```bash
plural verifier init verifier.yaml --name correct --kind deterministic
plural task init task.yaml --id order-a100 \
  --environment environment --verifier verifier.yaml
plural verifier validate verifier.yaml
plural task validate task.yaml
```

Implement the generated deterministic verifier command before execution. A
Verifier owns its runtime and connectivity independently. `--kind agent`
creates a model judge; `--kind human` creates a rubric that yields
`awaiting_review`.

The Task owns instructions, public `info`, metadata, one exact Environment
revision, and one or more weighted Verifier revisions.

## 3. Create an Agent

```bash
plural harness init harness --name support-loop
plural agent init agent.yaml --name candidate \
  --model openai/gpt-4.1-mini --harness harness
plural agent validate agent.yaml
```

`AgentDefinition` owns model, instructions, routing, and an optional Harness.
It does not contain an Environment identity. Harness compatibility and the
effective capability stamp are resolved separately for every planned Trial.

## 4. Run the Task directly

```bash
plural run task.yaml --agent agent.yaml --mode eval --dry-run
plural run task.yaml --agent agent.yaml --mode eval
plural run task.yaml --agent agent.yaml --mode eval --offline
```

Eval mode disables Rewarders and TITO capture but still runs final Verifiers.
The dry run computes stable Job/Trial identities and performs compatibility
preflight without launching a runtime. The normal run validates the complete
graph before any write, publishes Harnesses, Environments, Verifiers, Tasks,
an optional Benchmark, then Agents, submits the hosted Job with exact revision
IDs, prints it, and follows events. The offline form writes its durable log
under `.plural/jobs`; `--private` is equivalent.

## 5. Build a cross-Environment Benchmark

Create additional Task files in the same way. They may point at different
Environment revisions.

```bash
plural benchmark init benchmark.yaml --name support-suite \
  --task task.yaml --task another-task.yaml
plural benchmark validate benchmark.yaml
plural run benchmark.yaml --agent agent.yaml \
  --mode eval --attempts 2 --concurrency 4 --dry-run
```

Planning expands Agent × selected Task × attempts. An attempt is a distinct
Trial. Runtime retries append TrialExecutions beneath the same Trial.

For a reusable Job file:

```bash
plural job init job.yaml --source benchmark.yaml \
  --source-kind benchmark --agent agent.yaml
plural run job.yaml --dry-run
plural run job.yaml --no-watch --idempotency-key release-2026-09-10
```

Use `--source-kind task` when the Job source is a single Task. Without an
override, the stable local Job ID is also the hosted idempotency key.

## 6. Watch progress and human review

```bash
plural job watch JOB_ID --hosted --json
plural trial list JOB_ID
plural trial watch TRIAL_ID --job JOB_ID --json --follow
plural review list JOB_ID
plural review submit JOB_ID TRIAL_ID \
  --verifier human-review --score 1 --feedback approved
```

Progress events are durable, append-only, monotonic, and sanitized.
`plural run` already follows hosted Job events unless `--no-watch` is set.

## 7. Train mode

```bash
plural run task.yaml --agent agent.yaml --mode train
plural run task.yaml --agent agent.yaml --mode train --offline
```

Train mode enables Environment Rewarders and exact TITO capture. The Harness
must declare TITO support or preflight fails. Each record contains step,
tokenizer/model, input/output/observation token IDs, output log probabilities
and top log probabilities, output text, assistant message, and validated
`input_len`, `output_len`, and `observation_len`. Records are stored as hashed
artifacts instead of embedded in trace JSON.

See [package execution](package-tools.md) and the generated
[CLI reference](../reference/cli-commands.md).
