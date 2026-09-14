---
route: /docs/running/training
title: Training and RL
order: 105
description: Reuse project definitions for training with compatible exact token capture.
audience: all
nav: true
nav_group: Run
outcome: You understand what train mode requires and what a downstream trainer must do.
---
# Training and RL

Eval and train Jobs share the same project concepts. Both select Tasks, Agents, and final Verifiers. Train mode adds requirements for learning data and supports Environment rewarders; it does not itself update model weights.

## Begin with an evaluation you trust

Before collecting training data, check that your Verifiers distinguish known good and bad outcomes. Keep a held-out evaluation benchmark so you can test whether a change generalizes. Task metadata can label a split, but your data pipeline must enforce that separation.

## Exact tokens in, tokens out

Train mode requires a Harness that supports **TITO**, exact tokens in and
tokens out. Preflight checks the public Harness declaration and execution
validates the emitted artifact. A reconstructed prompt, a retokenized
transcript, or a list of game moves is insufficient.

A compatible public Harness declares:

```yaml
kind: harness
name: exact-token-loop
version: 1.0.0
command: [python, harness.py]
source: harness
artifacts:
  - path: tito.jsonl
    required: true
    media_type: application/jsonl
tito: tito.jsonl
```

`tito` derives internal support metadata; do not author internal support flags
or paths. This is a contract to implement, not a switch that makes a Harness
training-ready.

Each `TITORecord` includes `step`, `tokenizer`, `model`, exact
`input_token_ids`, `output_token_ids`, `observation_token_ids`, aligned
`output_logprobs` and `output_top_logprobs`, `output_text`,
`assistant_message`, and matching length fields. Values must come from the
actual model call. A reconstructed prompt, retokenized transcript, or action
list is insufficient.

The support starter uses a native Harness without exact token capture, so it should fail train preflight. Keep them in eval mode. Select or implement a Harness whose model provider exposes the required token data before using:

```bash
plural run training-job.yaml --mode train --offline
```

This command assumes you have authored `training-job.yaml` with a compatible Harness, runtime, and Tasks. It is not an additional quickstart command.

## Final Verifiers and rewarders

A final Verifier assesses completion of the Task. An Environment rewarder represents an additional learning signal, such as progress toward a solution. Train mode includes rewarders; eval mode skips them.

The package Job executor currently runs command Rewarders during final scoring,
using captured artifacts and `rewarder-result.json`. It does not automatically
call arbitrary Rewarder code after each native action. If an RL algorithm needs
transition-level rewards, its Environment/Harness integration must invoke and
record them.

Python rewarders described by implementation digests are not executable from package Jobs; they require the supported in-process path. A declaration alone does not provide a remote implementation.

The final Task reward remains the weighted aggregate of its Verifiers.
Rewarder outputs do not silently replace that evaluation metric.

## Validate before scaling

Run one complete training Trial before increasing concurrency. Confirm the TITO artifact exists, contains valid records, and corresponds to the actual model calls. Confirm the final Verifiers still receive their evidence. If a human Verifier is attached, finish the reviews before treating the dataset as fully scored.

Do not claim exact provenance by fabricating token IDs or setting a support flag on approximate data. Unsupported capture is a configuration problem to solve in the Harness/provider integration.

## Hand data to your trainer

The downstream workflow chooses eligible Trials, preserves revision and score provenance, applies redaction and split rules, and converts the records into the trainer's expected format. Training, checkpoint storage, and deployment are separate from the Job executor.

After updating the agent, run the held-out Benchmark in eval mode with the same scoring and runtime policy. Compare scores alongside completeness and behavior in the traces, not just a training reward curve.

Plural 0.12.1 intentionally does not implement SFT, DPO, PPO, GRPO, rollout
optimization, gradient updates, checkpoint storage, or deployment. It provides
versioned tasks, exact capture contracts, evidence, and evaluation before and
after an external training system.
