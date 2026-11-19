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
and `integrity`, which it can't.

`grader` and `task` both mean no Agent could have passed, and they are told apart by
what is wrong:

- **`grader`**: the answer key (the Task's `expected`) is right, but the Verifier's
  code judges a correct answer wrong, or a wrong one right.
- **`task`**: the answer key is wrong, or the request and its files leave out
  something needed to reach it.

To decide, the Inspector plays the Task's reference solution, which never sees the
answer key, through the same Environment and Verifiers, reusing the check `plural
task validate` saved when there is one. If the reference passes, the grading works
and the cause is the Agent's. If it fails too, the Inspector compares the request with
the answer key: a key that contradicts the request, or a request missing what the key
needs, is `task`; a right key judged wrongly is `grader`.

One cause can hide another. An Agent that failed early never reached the step where a
second weakness would show, so when a fork removes the first cause, the Inspector
checks the forked Trials for a second, and records it as its own Finding.

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

A `model` Finding needs more than an inference. It is recorded only when a fork that
switched the Agent to another model, and changed nothing else, beat its controls on the
gates the Finding explains: that fork is what shows a stronger model passes where this
one failed. Without one, `record_finding` refuses it and the Inspector keeps looking at
the instructions, tools, and context. So a `model` Finding is always `confirmed`, and
with forks off, or at `--depth quick`, the Inspector never records one.

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
Trials named, `--model` picks the Inspector's model (by default `openai/gpt-5.6-luna`, a
small, low-cost model), `--fork-model` limits the models a fork may switch the Agent to
(repeat it for several; by default any gateway model), and `--json` prints everything.

The forks never run with your own key. Each inspection mints a key of its own: it can
only call models through the gateway, is tagged with the Job it inspects for audit, is
stored as a hash, is never listed with your keys, and is revoked when the inspection
ends (or after three hours, if it never does). The gateway can't tell a fork's model
call from any other, so those are its limits: scope, expiry, and revocation. It reaches only the process that holds the
Inspector's App, never the Inspector's model or your Agent's Harness. Minting it needs
hosted access: sign in and bind the project, or scope your key with `plural auth scope
--project`. Without it, `--depth standard` and `deep` still run, with forks off, and
every Finding is `inferred`. Nothing the Inspector reads (rewards, State, the answer
key, Verifier code, or other Findings) ever reaches the Agent being tested.

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

This holds for every Harness. The native loop and the engine record the call
themselves. Claude Code and Codex answer such a call on their own and fire no hook
for it, so Plural reads it from their output as they run: Claude Code's event stream
names the tool and its arguments, and Codex's log names only the tool, so its step
has no arguments. A call that does reach the Environment's MCP server with an action
it doesn't have goes to the App host instead of being refused.

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
described tool, a wrong or contradictory instruction, a weaker model, padded context,
a broken Verifier, a wrong answer key, or a request missing its quantity), and keeps
each Trial the healthy Agent passed and the faulty one failed. A fault that breaks
nothing the healthy Agent passed has no cases, and `bench.json` lists it under
`ineffective`, beside any cause the faults claim that ended up with no cases. Two
faults escalate until they break something: the model fault tries weaker gateway
models in turn (`--weak-model` picks them), and the context fault pads the
instructions with about 40k, 200k, then 800k tokens (`--padding-lines` picks the
lengths). `--max-tasks` caps the Tasks each fault runs on, to bound what building the
bench costs. The bench is diagnosis, so it never runs a held-out Task. The Inspector
passes a bench Task when its Finding names the planted cause, a critical step the
answer key accepts, and words that name the fault. The critical step isn't scored when
the cause is `task` or `grader`: no step of the Agent's brought those about, so any
step, or none, is right. `run --fork-model` limits the models forks may switch to.

```bash
python -m plural.inspector.faults build examples/quoting /tmp/inspector-bench
python -m plural.inspector.faults run /tmp/inspector-bench
```

The injector is a development tool, not a command. Each group of cases runs with a
fork key minted for the Job its Trials came from, so `run` needs hosted access
(`PLURAL_API_KEY` and `--project`); without it, forks are off.

Measured on November 19, 2026, with the Inspector on `openai/gpt-5.6-luna` at
standard depth and a $0.25 fork budget per case, against quote-bot's model
`openai/gpt-5.6-luna`, on dev Tasks only, at most 12 per fault (`--max-tasks 12`), with
forks limited to `openai/gpt-5.6-luna`, `anthropic/claude-haiku-4-5`, and
`google/gemini-3.7-flash`. The Inspector's own model calls cost $0.11 for all 35
cases. The full result is
[`examples/quoting/inspector-bench.json`](https://github.com/lastlabs-ai/plural/blob/main/examples/quoting/inspector-bench.json).
"Before" is the same 35 cases earlier that day, before the two rules above: a `model`
Finding backed by a stronger model's fork, and no critical step scored for `task` or
`grader`.

| Fault | Cause | Right | Before |
| --- | --- | --- | --- |
| A tool hidden | tools | 3 of 4 | 3 of 4 |
| A tool described as optional | tools | 2 of 3 | 2 of 3 |
| Round the price | instructions | 3 of 4 | 4 of 4 |
| Always promise the requested date | instructions | 0 of 4 | 0 of 4 |
| Never hand off | instructions | 3 of 4 | 3 of 4 |
| A weaker model (Claude Haiku 4.5) | model | 2 of 4 | 2 of 4 |
| The Verifier checks the list price | grader | 2 of 4 | 4 of 4 |
| The answer key doubles the tons | task | 3 of 4 | 3 of 4 |
| The request leaves out the quantity | task | 4 of 4 | 0 of 4 |
| **All** | | **22 of 35 (63%)** | **21 of 35 (60%)** |

It named the planted cause in 27 of 35 cases, a step the answer key accepts in 13
of 21 cases that have one, and the fault in its own words in 32 of 35. Claude Haiku
4.5 was enough for the model fault. Padding broke nothing at 1,200 or 6,000 lines
(about 40k and 200k tokens), so the context fault has no cases; the 24,000-line level
was not run.

The missing quantity went from 0 to 4 of 4 by the bench rule alone: the Inspector
named `task` with no critical step both times. The model rule changed what the
Inspector concludes more than how often it is right. Before, it recorded 10 `model`
Findings, every one refuted by its own forks and 7 of them on faults that weren't the
model; now it recorded 3, each confirmed by a fork to another model, all on the weaker
model. Most of the cases it used to call `model` it now calls `instructions` at step
1, which is still a miss on the tool faults, the requested date, and the doubled answer
key. The two list-price
misses named `environment`, and the rounding miss `grader`; with four cases a fault,
one run moves a fault by a case or two either way.
