---
route: /docs/tutorials/package-tools
title: "Add actions, verification, and training capture"
order: 60
description: "Continue from the CLI walkthrough."
audience: all
---
# Add actions, verification, and training capture

Continue from the [CLI walkthrough](cli-walkthrough.md).

## Environment actions and runtime

Declare native actions in `environment/environment.yaml`:

```yaml
actions:
  - name: lookup_order
    description: Look up an order.
    kind: command
    command: [python, lookup_order.py]
    parameters:
      type: object
      properties:
        order_id: {type: string}
      required: [order_id]
      additionalProperties: false
runtime:
  provider: docker
  image: python:3.12-slim
  network: none
  targets: [docker]
```

Environment owns this runtime, including provider, placement, network,
resources, and secrets. Job files cannot override it.

When `AgentDefinition.harness` is `None`, native actions are exposed through
the built-in native protocol. An external Harness brings its own action loop;
its compatibility and capability stamp are resolved against the Environment
per Trial.

## Deterministic, agent, and human Verifiers

Create Verifiers independently:

```bash
plural verifier init correct.yaml --name correct --kind deterministic
plural verifier init judge.yaml --name judge --kind agent
plural verifier init review.yaml --name human-review --kind human
```

A deterministic Verifier runs its command. An agent Verifier runs a model
against its rubric. Both own runtime/connectivity independently from the task
Environment. A human Verifier launches no runtime and moves the Trial to
`awaiting_review`.

Pin one or more Verifiers on a Task:

```bash
plural task init task.yaml --id order-a100 \
  --environment environment \
  --verifier correct.yaml --verifier judge.yaml
```

Edit `verifier_weights` in the Task file when weights are not all `1.0`.
Successful finite rewards aggregate by normalized weight in declaration order,
so identical revision graphs produce identical totals.

## Eval and train

```bash
plural run task.yaml --agent agent.yaml --mode eval
plural run task.yaml --agent agent.yaml --mode train
plural run task.yaml --agent agent.yaml --mode eval --offline
```

Eval always executes final Verifiers but disables Environment Rewarders and
TITO. Train enables Rewarders and requires exact TITO support from the selected
Harness. The first two commands synchronize and submit hosted Jobs by default;
the explicit offline form executes locally and stores its durable log under
`.plural/jobs`. `--private` has the same behavior.

A TITO JSONL record must include:

- `step`, `tokenizer`, and `model`;
- `input_token_ids`, `output_token_ids`, and `observation_token_ids`;
- `output_logprobs` and `output_top_logprobs`, each aligned to output tokens;
- `output_text` and `assistant_message`;
- validated `input_len`, `output_len`, and `observation_len`.

The engine validates lengths and finite probabilities before storing the JSONL
as an immutable SHA-256-addressed artifact. Trace and event payloads carry only
artifact references, never the giant token arrays.

## Observe and complete review

```bash
plural job watch JOB_ID --hosted --json
plural review list JOB_ID
plural review submit JOB_ID TRIAL_ID \
  --verifier human-review --score 1 --feedback approved
```

Review submission appends durable state; it does not rewrite prior progress
events or TrialExecutions.
