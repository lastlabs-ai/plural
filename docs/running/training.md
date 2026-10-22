---
route: /docs/running/training
title: Training and RL
order: 105
description: When no model is good enough yet, reuse your Tasks and graders to collect training data, hand it to your own trainer, and check the result on held-out Tasks.
audience: all
nav: true
nav_group: Run
outcome: You understand what train mode requires and what a downstream trainer must do.
---
# Training and RL

Sometimes evaluation shows that even the best model keeps making the same kind of
mistake. Training is how you fix that. Plural lets you reuse the Tasks,
Environments, and Verifiers you already built to collect graded training runs,
then test the improved model on the same kind of work.

Plural prepares the learning data; it does not train the model. Updating model
weights, storing checkpoints, and deploying a trained model require a separate
training system.

## Scores and rewards

Two numbers matter here, and they do different jobs:

- A **score** comes from the Verifiers, the graders, at the end of an attempt. It
  says how well the Task went, and it is the only thing a Benchmark ranks on.
- A **reward** is small credit for one move, or one stretch of a trajectory, such as
  getting closer to the answer. A training algorithm uses rewards to work out
  which moves helped. Rewards count toward the score only when a Verifier's `check`
  is `total_reward`, and the Agent never sees them.

The steps below use both.

## 1. Establish a baseline

Run the Agent in eval mode and inspect its failures. Confirm that the Environment
gives it the information and actions needed to succeed, and that the Verifiers
score correctly. Fix setup problems before treating low scores as model
weaknesses.

Reserve a held-out Benchmark for evaluation. Task metadata can label training and
evaluation splits, but your data pipeline must keep them separate.

## 2. Choose a Harness with exact token capture

Train mode requires **TITO**, short for exact tokens in and tokens out: the precise
token IDs the model received and produced on every call. These records connect
the model's actual inputs and outputs to the resulting actions and scores.

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
returned records to `tito.jsonl`. In train mode, a Trial whose Harness does not
declare `supports_tito` fails with a `tito_unsupported` error, and a Trial whose
records are missing, empty, or invalid fails with `evidence_missing` or
`artifact_failed`. The support queue and Wordle examples use ordinary evaluation
Harnesses and cannot run in train mode as supplied.

Each `TITORecord` includes the step, tokenizer, model, exact input, output, and
observation token IDs, matching lengths, output text, assistant message, and
aligned output log probabilities. Values must come from the actual model call.
Retokenizing a saved transcript is not equivalent.

## 3. Collect one training Trial

Train mode is set on the Python `Job`; `plural run` always runs in eval mode.
Given a Task and an Agent whose Harness captures TITO, check the plan and then run
it:

```python
from plural import Client, Job
from plural.jobs import JobMode
from plural.project import Project, Workspace

workspace = Workspace(Project.find())
task = workspace.get("task", "ticket-1")
agent = workspace.get("agent", "exact-token")
job = Job(task, agents=[agent], mode=JobMode.TRAIN, client=Client())
print(job.plan.trial_count)
result = job.run()
```

This assumes your project defines that Task and Agent and that a Plural API key is
available, stored with `plural auth login --api-key-stdin` or set as
`PLURAL_API_KEY`.

> **Tip:** Start with one Task and one attempt. Before increasing concurrency,
> inspect the token artifact, trajectory, final State, and Verifier results.
> Complete any pending human reviews before using the run as fully scored data.

## 4. Add rewards where needed

Final Verifiers measure Task success in both eval and train mode. Rewards provide
the finer signal an algorithm needs to assign credit, such as progress toward a
solution. Every reward a Trial earns goes in its **reward ledger**, `rewards.jsonl`
in the Trial's artifacts, whatever produced it. Each line names its source, its
verifier and version, its value, and its target: a step, a model call, or a span of
text or tokens within one. Rewards never reach the Agent.

There are two ways to produce them.

**While the episode runs.** A Task's Verifier can have a `reward` function, which runs right
after each action, beside the Apps, and can read every App. Because it belongs to the
Task, the same Environment can be rewarded differently for different Tasks. See
[Reward each step](../project/verifiers.md#reward-each-step). Train mode also
writes each step's reward as a `reward` event in the Job's progress events.

**After the episode, in hindsight.** A Verifier's `hindsight` function reads a whole
finished Trial, including its score, every step, and each App's final State, and
credits whichever moves deserve it. It suits signals you can only judge at the end,
such as "the guess that solved it, weighted by how few it took". It runs on every
Trial of a Task that lists the Verifier. See
[Credit in hindsight](../project/verifiers.md#credit-in-hindsight).

### Label stored Trials

Rewards are often designed after the data exists. Edit a Verifier's `reward` or
`hindsight`, then see what it would give on Trials you already ran. Nothing runs the
Agent again, and nothing is saved:

```bash
plural verifier try solved --job JOB_ID
```

```text
TRIAL_ID: score 1, 5 step rewards totalling +1, 1 hindsight totalling +0.7
  step  e2     +0.000  step
  step  e3     +0.000  step
  step  e4     +0.000  step
  step  e5     +1.000  step
  step  e5     +0.700  hindsight
```

`reward` runs again on each recorded step, against the State each App had at that
step, and `hindsight` on the finished trajectory. When the numbers look right, bump
the Verifier's `version` and record them:

```bash
plural verifier apply solved --job JOB_ID
plural reward show TRIAL_ID
```

```text
step  e5     +1.000  step:solved@0.1.0
step  e5     +1.000  step:solved@0.2.0
step  e5     +0.700  hindsight:solved@0.2.0
```

Each version's records sit beside the others, so an export can pick which labels to
use. A Trial that already has records from the Verifier's current version is left as
it is.

If you recorded the Job with `plural job record` or `--record`, `apply` adds the new records to the
hosted Trials' ledgers too, where the Trial page shows each reward on the step it
credits. Each record is stored once, so applying again never duplicates one.

The final Task score remains the weighted aggregate of its Verifiers. Rewards
contribute to it only through a Verifier whose `check` is `total_reward`. Keep that
evaluation metric stable as you experiment with rewards.

## 5. Export training data

`plural reward export` writes one JSON line per Trial, joining its trajectory with its
reward ledger:

```bash
plural reward export --job JOB_ID --out training.jsonl
```

Each line has the Trial's `score`, and `turns`: one entry per model call, with the
reward credited to it, any span rewards mapped onto token positions, and its TITO
record when the Trial captured one. A step's reward is credited to the model call
whose turn issued the action. The options choose which labels to use:

- `--verifier NAME` or `--verifier NAME@VERSION` keeps only those verifiers. By
  default every verifier is used, at its latest version.
- `--aggregate sum|mean|last` combines several rewards on one target. The default is
  `sum`.
- `--include-off-recording` keeps rewards on steps where a replayed App answered a
  call its recording didn't cover. They are left out by default, because the
  recording can't vouch for them.

## 6. Train and evaluate again

Select eligible Trials, preserve their Task and Agent versions and scores, and
convert the export into your trainer's format. Apply your data access,
redaction, and split rules before export.

After training, make the updated model available through a supported endpoint and
create a new Agent version. Run the held-out Benchmark with the same scoring and
Runtime policy. Compare quality, cost, latency, and failure patterns before
changing application routing.

See [Providers and integrations](../reference/integrations.md#route-after-evaluation)
for using evaluation results to choose models for application requests.
