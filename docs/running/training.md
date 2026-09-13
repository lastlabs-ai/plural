---
route: /docs/running/training
title: Training data and reward signals
order: 105
description: Reuse project definitions for training with compatible exact token capture.
audience: all
nav: false
outcome: You understand what train mode requires and what a downstream trainer must do.
---
# Training data and reward signals

Eval and train Jobs share the same project concepts. Both select Tasks, Agents, and final Verifiers. Train mode adds requirements for learning data and supports Environment rewarders; it does not itself update model weights.

## Begin with an evaluation you trust

Before collecting training data, check that your Verifiers distinguish known good and bad outcomes. Keep a held-out evaluation benchmark so you can test whether a change generalizes. Task metadata can label a split, but your data pipeline must enforce that separation.

## Exact tokens in, tokens out

Train mode requires a Harness that supports **TITO**, exact tokens in and tokens out. The package preflight checks `supports_tito`; execution validates the artifact it emits. A reconstructed prompt, a retokenized transcript, or a list of game moves is insufficient.

A compatible Harness declares this fragment:

```yaml
supports_tito: true
tito_path: tito.jsonl
artifacts:
  - path: tito.jsonl
    required: true
    media_type: application/jsonl
```

This is a contract to implement, not a switch that makes any Harness training-ready. Each JSONL record must satisfy `TITORecord`, including its exact token provenance. See the [definition reference](../reference/definitions.md#training-records) for fields and the generated schema for validation.

The support starter uses a native Harness without exact token capture, so it should fail train preflight. Keep them in eval mode. Select or implement a Harness whose model provider exposes the required token data before using:

```bash
plural run training-job.yaml --mode train --offline
```

This command assumes you have authored `training-job.yaml` with a compatible Harness, runtime, and Tasks. It is not an additional quickstart command.

## Final Verifiers and rewarders

A final Verifier assesses completion of the Task. An Environment rewarder represents an additional learning signal, such as progress toward a solution. Train mode includes rewarders; eval mode skips them.

The package Job executor currently runs command rewarders during final scoring, using captured artifacts and a result file named `rewarder-result.json`. It does not automatically call arbitrary rewarder code after each native action. If your learning algorithm needs transition-level rewards, implement and record that behavior in the appropriate Environment/Harness integration.

Python rewarders described by implementation digests are not executable from package Jobs; they require the supported in-process path. A declaration alone does not provide a remote implementation.

The final Task reward remains the weighted aggregate of its Verifiers. Rewarder outputs do not silently replace that evaluation metric. Keep learning signals and final success scores identifiable in your downstream records.

## Validate before scaling

Run one complete training Trial before increasing concurrency. Confirm the TITO artifact exists, contains valid records, and corresponds to the actual model calls. Confirm the final Verifiers still receive their evidence. If a human Verifier is attached, finish the reviews before treating the dataset as fully scored.

Do not claim exact provenance by fabricating token IDs or setting a support flag on approximate data. Unsupported capture is a configuration problem to solve in the Harness/provider integration.

## Hand data to your trainer

The downstream workflow chooses eligible Trials, preserves revision and score provenance, applies redaction and split rules, and converts the records into the trainer's expected format. Training, checkpoint storage, and deployment are separate from the Job executor.

After updating the agent, run the held-out Benchmark in eval mode with the same scoring and runtime policy. Compare scores alongside completeness and behavior in the traces, not just a training reward curve.
