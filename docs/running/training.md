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
  which moves helped. Rewards never count toward the score, and the Agent never
  sees them.

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
from plural import Client, Job, JobMode
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
rewarder and version, its value, and its target: a step, a model call, or a span of
text or tokens within one. Rewards never reach the Agent and never count toward the
score.

There are two ways to produce them.

**While the episode runs.** A `@rewarder` on an App runs right after each of that
App's actions, and the Environment's `on_step` can return one for any action. See
[Rewards](../project/environments.md#rewards) for how to declare them. Train mode also
writes each step's reward as a `reward` event in the Job's progress events.

**After the episode, in hindsight.** A hindsight rewarder reads a whole finished
Trial, including its score, every step, and each App's final State, and credits
whichever moves deserve it. It suits signals you can only judge at the end, such as
"the guess that solved it, weighted by how few it took", or labels you decide on
later:

```python
from plural import HindsightTrial, hindsight_rewarder


@hindsight_rewarder(version="1")
def fewer_guesses(trial: HindsightTrial):
    """Credit the solving guess more when it took fewer guesses."""
    guesses = trial.steps("guess")
    if trial.score:
        yield trial.credit(guesses[-1]["event_id"], 1.0 - 0.1 * (len(guesses) - 1))
```

`trial.steps(action)` lists the Environment steps, `trial.model_calls()` the model
calls, and `trial.apps` each App's initial and final State. Bump `version` when the
logic changes, so an export can pick which labels to use.

Run it on Trials you already have. This labels a stored Job without running anything
again, and works the same on [recorded traces](traces.md#score-traces-you-already-have):

```bash
plural rewards apply rewarders.py:fewer_guesses --job JOB_ID
plural rewards show TRIAL_ID
```

```text
step  e2     +0.000  app:solved
step  e3     +0.000  app:solved
step  e4     +0.000  app:solved
step  e5     +1.000  app:solved
step  e5     +0.700  hindsight:fewer_guesses@1
```

Or pass `hindsight=[fewer_guesses]` to the `Job` to label each Trial as it finishes.

The final Task score remains the weighted aggregate of its Verifiers. Rewards
never contribute to it. Keep that evaluation metric stable as you experiment with
rewards.

## 5. Export training data

`plural rewards export` writes one JSON line per Trial, joining its trajectory with its
reward ledger:

```bash
plural rewards export --job JOB_ID --out training.jsonl
```

Each line has the Trial's `score`, and `turns`: one entry per model call, with the
reward credited to it, any span rewards mapped onto token positions, and its TITO
record when the Trial captured one. A step's reward is credited to the model call
whose turn issued the action. The options choose which labels to use:

- `--rewarder NAME` or `--rewarder NAME@VERSION` keeps only those rewarders. By
  default every rewarder is used, at its latest version.
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
