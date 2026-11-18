---
route: /docs/running/inspector
title: Find out why an Agent fails
order: 89
description: The Inspector explains each failed Trial with a cause and its evidence, tests Agent causes with forks, turns a confirmed cause into a new Agent version, and reports the numbers.
audience: all
nav: true
nav_group: Run
---
# Find out why an Agent fails

A score tells you how often an Agent fails. The **Inspector** tells you why. It is an
Agent built on Plural, like yours: it reads a failed Trial's evidence through
read-only tools, names the step where the Trial went wrong and the cause, and, when
the cause is something about your Agent, tests it by [forking](forks.md) the Trial
with the cause removed. Each cause it finds is a **Finding**. A Trial that failed for
two independent reasons, such as a wrong price and a date the mill can't meet, gets
one for each.

```bash
plural job inspect job_7e9fb7741358c5191bc0e413
```

```text
Inspected 30 of 30 failed Trials of Job job_7e9fb7741358c5191bc0e413 (standard), $4.15:
  instructions   23   77%  20 confirmed
  model           5   17%  0 confirmed
  grader          3   10%  0 confirmed
  tools           2    7%  1 confirmed
F1 trl_0c4c9d039816ff11b163e147 quote-002: instructions, confirmed, step 5, explains price_correct
   The Agent rounded the tool-returned market price from $1,225.55/t to $1,226/t exactly
   as its pricing instructions required, but the price gate required the unrounded
   latest price.
   fork X1 (job_beac2b4f0a6151cd9cf2c091) on price_correct: likely matters
...
F23 trl_0d6ae3662d630480c3443cfc quote-036: tools, confirmed, step 5, explains delivery_feasible
   The Agent skipped the schedule check because its description labeled it optional,
   then promised the customer's requested date.
   fork X2 (job_c141b3ace93432adbec7582a) on delivery_feasible: no clear effect
   fork X3 (job_16a63f356435fd8261867623) on delivery_feasible: likely matters
...
```

That is the quoting example's quote-bot on its 46 dev Tasks. quote-036 failed two
gates for two causes, so it has a Finding for each: F22 for the rounding rule and F23
for the schedule tool.

Only dev Trials are inspected. Held-out Trials are never shown to the Inspector, so
what it learns can't leak into the set you confirm a fix on.

## What a Finding says

| Field | What it holds |
| --- | --- |
| `critical_step` | The first step after which the Trial could no longer succeed. |
| `cause` | A cause dimension, below. |
| `gates` | The Trial's failed gates this cause explains. Every failed gate is explained by some Finding. |
| `summary` | The cause, in a sentence or two. |
| `evidence` | What in the Trial shows it: steps, State, the Verifier's output. At least one item. |
| `forks` | Each fork that tested it, with how often each side passed and the verdict. |
| `status` | `confirmed`, `inferred`, `refuted`, or `inconclusive`, computed from the forks. |
| `remedy` | For an Agent cause, the change the forks tested. |

The **cause dimensions** are `model`, `context`, `tools`, `instructions`, and
`harness`, which a change to the Agent can fix, and `environment`, `grader`, `task`,
and `integrity`, which it can't. A wrong answer key is `grader`: the Agent's work was
right and the grading wasn't. A request that can't be answered as written is `task`.

A fork is judged on the gates its Finding explains, so a fix for one of two failures
shows its effect even though the Trial still fails the other. Each fork also reports,
for each side, how many Trials passed whole and how many failed each gate. When the
candidates stop failing one gate but start failing another, the Inspector refines the
change and forks again; when the fix works and the Trial still can't pass, it looks
for a second cause, often a wrong answer key, and must record it before it finishes.

The **status** is computed, never chosen by the model. A Finding is `confirmed` when a
fork with its remedy passed more often than the controls, with an interval that
excludes zero; `refuted` when its forks decided and none did; a fork judged on other
gates than the Finding's tested something else and doesn't count; `inconclusive` when
they had too few Trials to decide; and `inferred` when nothing was forked. A fork
changes the Agent, so it can't confirm a cause outside the Agent: a `grader` or `task`
Finding is always `inferred`, and its evidence is what supports it.

`plural job inspect` saves the Findings beside the Job as `findings.json`, and, for a
Job you recorded, on the hosted Job, where the **Why it failed** tab shows the
breakdown and each Finding.

### Depth and budget

| `--depth` | What it does |
| --- | --- |
| `quick` | Reads the evidence and records Findings, with no forks. Every Finding is `inferred`. |
| `standard` | Forks to test an Agent cause, four Trials a side. The default. |
| `deep` | Forks every plausible Agent cause, six Trials a side. |

`--budget-usd` caps what forks may spend across the Job, split evenly over the failed
Trials; the Inspector is refused a fork it can't afford. `--trial` inspects only the
Trials named, `--model` picks the Inspector's model, and `--json` prints everything.

The forks run with your Plural key, which reaches only the process that holds the
Inspector's App. Neither the Inspector's model nor your Agent's Harness ever sees it.
Nothing the Inspector reads (rewards, State, the answer key, Verifier code, or other
Findings) ever reaches the Agent being tested.

## Ask about one Trial

```bash
plural trial ask trl_0c4c9d039816ff11b163e147 "Did it ever check the schedule?"
```

The Inspector answers from the same evidence tools, without forking.

## Teach it about your project

The Inspector reads three optional files in your project's `inspector/` folder:

- **`signals.py`**: your own checks over a Trial, which the Inspector sees first.
  Each is a function marked `@signal`:

  ```python
  from plural.inspector.signals import Signal, signal

  @signal("quoted_without_schedule")
  def quoted_without_schedule(trial):
      actions = [step.get("action") for step in trial.steps]
      if "submit_quote" in actions and "check_schedule" not in actions:
          yield Signal("quoted_without_schedule", actions.index("submit_quote") + 1,
                       "quoted a date without checking the schedule")
  ```

  Built in: `unknown_action`, `action_error`, `repeated_action`, `unused_tool`,
  `failed_gate`, `stop_reason`, and `large_context`. A signal that raises is reported
  as `signal_failed`, never fatal.
- **`causes.yaml`**: cause dimensions of your own, each with a description and whether
  a change to the Agent can fix it.
- **`patterns.yaml`**: failure patterns people have already found, as a list of
  `{name, description}`. The Inspector checks them before looking further.

## Calls to tools that don't exist

When a model calls a tool the Agent wasn't offered, such as one it made up or one its
`tool_overrides` hide, the call is recorded as a step with `unknown_action` in its
info, never run, and the model is told the action doesn't exist. It never names the
other actions, so a hidden one stays hidden. The `unknown_action` signal points the
Inspector at these steps.

## Turn a Finding into a new Agent version

```bash
plural agent revise quote-bot --from-finding F1
```

`revise` applies a **confirmed** Finding's remedy to `agents/quote-bot/agent.yaml`,
raises its minor version, and adds an entry to `CHANGELOG.md` beside it: the Finding,
what changed, its evidence, and the forks that confirmed it, with their counts. A
remedy can change the instructions, the model, the Harness config, or a tool's
description in [`tool_overrides`](../project/agents.md#change-what-a-tool-says). The
comments at the top of `agent.yaml` are kept. `--job` picks the inspected Job when
several hold an `F1`.

It refuses a Finding that isn't confirmed, and one whose cause a change to the Agent
can't fix, such as `grader`. An [External Agent](../project/external-agents.md) runs as
its own service, so Plural can't change it or fork it with a remedy; `revise` writes
`agents/NAME/fixes/F1.md` for its team instead, with the cause, the evidence, and the
suggested change.

Then prove the new version on Tasks it was never tuned against:

```bash
plural run -b quoting -a quote-bot --heldout
plural job report NEW_JOB --compare OLD_JOB
```

## Report on a Job

```bash
plural job report job_7e9fb7741358c5191bc0e413 --compare job_31c0... --findings
```

A report has four sections:

1. **How the Agent performs**: pass rate, success rate, and mean score with its 95%
   interval, on dev and held-out Tasks, and every metric with its interval.
2. **Why it fails**: the breakdown by cause, and with `--findings`, each Finding.
3. **What changed**: with `--compare`, a paired comparison of the two Jobs on the
   Tasks both ran, on pass rate and on success rate, separately for dev and held-out
   Tasks, each with a verdict (`better`, `worse`, `within_noise`, `not_enough_data`).
4. **Why the numbers can be trusted**: trust tiers, integrity findings, and which Tasks
   passed their checks.

Code computes every number. Each is a **fact** with an id and the Trials it came
from, listed at the end of the report. With `--summary`, a model writes a short
summary, but it may only cite facts by id, such as `{N3}`, which are replaced with
the computed values. A summary that writes a number itself is rejected and asked for
again; if it still does, the report says so and has no summary.

The report is written to `.plural/jobs/JOB/report.md` and `report.json`, and to the
hosted Job's **Report** tab for a recorded Job.

## How accurate it is

inspector-bench measures the Inspector on failures whose cause is known. It starts
from a healthy quoting Agent, plants one fault at a time (a hidden or vaguely
described tool, a wrong or contradictory instruction, padded context, a broken
Verifier, a wrong answer key, or a request missing its quantity), and keeps each
Trial the healthy Agent passed and the faulty one failed. The Inspector passes a bench
Task when its Finding names the planted cause, a critical step the answer key
accepts, and words that name the fault.

```bash
python -m plural.inspector.faults build examples/quoting /tmp/inspector-bench
python -m plural.inspector.faults run /tmp/inspector-bench
```

Measured on November 18, 2026, with the Inspector on `openai/gpt-5.6` at standard
depth and a $0.50 fork budget per case, against quote-bot's model
`openai/gpt-5.6-luna`. The full result is
[`examples/quoting/inspector-bench.json`](https://github.com/lastlabs-ai/plural/blob/main/examples/quoting/inspector-bench.json).

| Fault | Cause | Cases | Right |
| --- | --- | --- | --- |
| A tool hidden | tools | 4 | 3 |
| Round the price | instructions | 4 | 4 |
| Always promise the requested date | instructions | 4 | 2 |
| Never hand off | instructions | 4 | 4 |
| The Verifier checks the list price | grader | 4 | 4 |
| The answer key doubles the tons | grader | 4 | 4 |
| The request leaves out the quantity | task | 4 | 0 |
| **All** | | **28** | **21 (75%)** |

It named a step the answer key accepts in 16 of 20 cases that have one, and named
the fault in its own words in 27 of 28. Two faults broke nothing the healthy Agent
passed, so they have no cases: a vague schedule-tool description, and 1,200 lines of
padding in the instructions.

All four misses on the missing quantity recorded `grader`: the Agent rightly handed
off a request with no quantity, and the answer key still wanted a quote. That fits
the definitions above as well as `task` does; the line between a wrong answer key
and a broken Task is not settled yet.
