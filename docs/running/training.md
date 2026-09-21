---
route: /docs/running/training
title: Training and RL
order: 105
description: Collect scored training data, connect an external trainer, and measure improvement on held-out Tasks.
audience: all
nav: true
nav_group: Run
outcome: You understand what train mode requires and what a downstream trainer must do.
---
# Training and RL

When evaluation reveals a consistent weakness, use those failures to decide what training should improve. Plural reuses your Tasks, Environments, and Verifiers to collect scored training runs and evaluate the agent afterward.

The package's train mode prepares learning data; it does not implement model optimization. Updating model weights, storing checkpoints, and deploying a trained model require a separate training system.

## 1. Establish a baseline

Run the agent in eval mode and inspect its failures. Confirm that the Environment gives it the information and actions needed to succeed, and that the Verifiers score correctly. Fix setup problems before treating low scores as model weaknesses.

Reserve a held-out Benchmark for evaluation. Task metadata can label training and evaluation splits, but your data pipeline must keep them separate.

## 2. Choose a Harness with exact token capture

Train mode requires **TITO**, or exact tokens in and tokens out. These records connect the model's actual inputs and outputs to the resulting actions and scores.

A compatible class-based Harness enables token capture and returns the exact
records:

```python
from plural import Harness, HarnessResult


class ExactTokenHarness(Harness):
    name = "exact-token-loop"
    supports_tito = True

    def run(self, task, agent, environment):
        # Capture these values from the actual model call.
        records = (...)
        return HarnessResult(
            response="complete",
            tito=records,
        )
```

The Harness must implement capture and return the records. Setting
`supports_tito = True` alone does not provide that behavior; Plural writes the
returned records to `tito.jsonl`. The support queue and Wordle examples use
ordinary evaluation Harnesses and cannot run in train mode as supplied.

Each `TITORecord` includes the step, tokenizer, model, exact input/output/observation token IDs, matching lengths, output text, assistant message, and aligned output log probabilities. Values must come from the actual model call. Retokenizing a saved transcript is not equivalent.

## 3. Collect one training Trial

After configuring a Job with a compatible Harness and provider, validate and run it:

```bash
plural validate training-job.yaml
plural run training-job.yaml --mode train --dry-run
plural run training-job.yaml --mode train
```

These commands assume you have created `training-job.yaml` and configured model authentication. Start with one Task and one attempt. Before increasing concurrency, inspect the token artifact, trajectory, final state, and Verifier results. Complete any pending human reviews before using the run as fully scored data.

## 4. Add learning signals where needed

Final Verifiers measure Task success in both eval and train mode. Rewarders provide the per-step signal an algorithm needs to assign credit, such as progress toward a solution.

Every Rewarder runs inside `step`, immediately after the action that changed the world, and its value is recorded on the episode in both modes. Train mode is what emits those values as a training signal. `info["rewards"]` breaks each step's total down by name, so you can see which action earned the credit. See [Rewards](../project/environments.md#rewards) for how to declare them.

The final Task score remains the weighted aggregate of its Verifiers. Rewards never contribute to it. Keep that evaluation metric stable as you experiment with learning signals.

## 5. Train and evaluate again

Select eligible Trials, preserve their Task and Agent versions and scores, and convert the records into your trainer's format. Apply your data access, redaction, and split rules before export.

After training, make the updated model available through a supported endpoint and create a new Agent version. Run the held-out Benchmark with the same scoring and Runtime policy. Compare quality, cost, latency, and failure patterns before changing application routing.

See [Providers and integrations](../reference/integrations.md#route-after-evaluation) for using evaluation results to choose models for application requests.
