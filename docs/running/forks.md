---
route: /docs/running/forks
title: Checkpoints and forks
order: 87
description: Continue a finished Trial from any step with another Agent, a change, or nothing changed, and see whether the difference is real.
audience: all
nav: true
nav_group: Run
---
# Checkpoints and forks

A **fork** continues a finished Trial from the moment after one of its steps. The
world is put back exactly as it stood: every App's State and random number
generators, the step and turn counters, and the Agent's workspace files. Then an
Agent carries on from there. That lets you ask a precise question about a failure,
such as "if the Agent had known the rounding rule at step 4, would it have
quoted correctly?", without rerunning everything before step 4.

A **checkpoint** is that moment: everything needed to restart the Trial after step
*k*. Plural builds one from a Trial's record whenever you fork. You can also save
one by name, to fork from again later or to start a Task there.

## Fork a Trial

```bash
plural trial fork trl_5adfefe943e4 --step 4 --agent quote-bot-v2 --attempts 3
```

This runs a fork Job. For each `--agent`, it runs `--attempts` **candidate** Trials
from step 4. Beside them, it runs as many **control** Trials: the original Agent,
unchanged, from the same checkpoint. Controls tell you how often the original
failure comes back on its own, so a difference you see is more than chance.

The command prints, for each candidate Agent:

- how many of its forks passed, and how many controls did;
- a verdict: `likely_matters` when the 95% interval of the difference in pass rate
  excludes zero, `no_clear_effect` when it does not, and `too_few` when either side
  has fewer than three Trials;
- how often the controls reproduced the original Trial's outcome. If they rarely
  do, the failure is mostly chance, and no fork will tell you much.

A Trial passes when every gate on its Verifiers' metrics passes. Without gates, a
score of 1 counts as a pass. Numbers in the summary are computed from the Trials;
nothing in them is written by a model.

To test a fix for one of several failures, judge both sides on the gates it should
fix, so the Trial still failing another gate doesn't hide its effect:

```bash
plural trial fork trl_5adfefe943e4 --step 4 --agent quote-bot-v2 --gate price_correct
```

Repeat `--gate` for several. A side's Trial passes when each named gate passed. A
name that isn't one of the original Trial's gates is refused before anything runs.

Use `--checkpoint NAME` instead of `--step` to fork from a saved checkpoint, and
`--json` for the full result. `--record` records the fork Job in your hosted
project, where each fork Trial shows where it started and the original Trial lists
its forks.

### Fork from the web app

On a finished Trial's page, **Fork from here** builds the command for you. Run it
in any folder linked to the Trial's hosted project. When this folder recorded the
Trial, Plural uses its local record. Otherwise it restores the exact Task and Agent
revisions the Trial ran into `.plural/versions/`, downloads the Trial's step, State
and workspace records into `.plural/hosted-trials/`, and forks from those. Anyone
who can read the Trial can fork it. `plural trial checkpoint` works the same way.

## How the history reaches the Agent

The world is restored exactly. The Agent's memory of the first *k* steps is the
part that can differ, and one rule decides it:

1. **Native.** When the new Agent was offered every tool the history used, it gets
   the history as its own conversation and carries on as if it had made those
   calls itself.
2. **Transcript.** When it lacks some of those tools, such as a Claude Code
   history forked into Codex, it gets the history as a transcript in its first
   message. Plural prints which tools were missing.
3. **None.** When it can't accept a history at all, such as an External Agent that
   doesn't declare `supports_resume`, it starts from the restored world with no
   history. Plural prints why.

Each fork Trial records which one it got, and the fork summary counts them.
Compare forks with the same kind of history when you can.

A Harness says whether it can continue a conversation with `supports_resume`, and
which tools it brings itself with `tools`. See [Harnesses](../project/harnesses.md).

## Change one thing at the fork point

A fork into another Agent tests a change you could ship. A **diagnostic** fork
changes one moment of the episode instead, to find out what caused a failure:

```bash
plural trial fork trl_5adfefe943e4 --step 4 --change message \
  --payload '{"text": "Quotes round to the nearest cent, half up."}'
```

The change applies to the candidates only; the controls run unchanged. These
changes are built in:

| Change | Payload | What it does |
| --- | --- | --- |
| `observation` | `{text}` | Replaces what the Agent sees after step *k*. |
| `message` | `{text}` | Adds a note to the Agent's next turn. |
| `action` | `{action, arguments}` | Takes this action as the next step, recorded as an intervention. |
| `tool_description` | `{tool, description}` | Rewrites one tool's description. |
| `context` | `{mode: trim, keep}`, `{mode: summarize, summary}`, or `{mode: fresh}` | Keeps only the last messages, replaces the history with a summary, or drops it. |
| `oracle_tool` | `{name, description, path}`, and `app` when there are several | Offers one more tool that returns one value from an App's State. |

An oracle tool answers with the value at `path` in the App's State when the Agent
calls it, such as `secret` or `quote.unit_price`, with `.` between keys and list
indexes. That one value is all of the State it shows, and it is shown only to the
candidates of a diagnostic fork, which is never shipped. It never reads the Task's
answer key.

```bash
plural trial fork TRIAL --step 2 --change oracle_tool \
  --payload '{"name": "peek", "description": "The secret word.", "path": "secret"}'
```

## Forks of a Trial several Agents share

In a Task with seats, `--seat` names the seat whose Agent is replaced. The other
seats keep their Agents and continue with their own histories.

## Save a checkpoint

```bash
plural trial checkpoint trl_5adfefe943e4 --step 4 --name before-rounding
```

The checkpoint is saved with the Trial. Fork from it with `--checkpoint
before-rounding`, or start a Task there with `from_checkpoint:
trl_5adfefe943e4/before-rounding`. See [Tasks](../project/tasks.md).

A checkpoint warns about what it can't carry over. A process the Agent left running
in the background, such as a dev server, is not restored, and the checkpoint says
so.

## What a fork needs

- **Restorable Apps.** Every App must be able to put its State back. A Python App
  can by default. An MCP or OpenAPI App needs `snapshot` and `restore` commands and
  a snapshot after every step. A `live` App never can.
  [Environments](../project/environments.md) shows whether an Environment is
  forkable, and why not.
- **Step records.** The Trial's steps, App States, and workspace snapshots. Every
  local run keeps them, and a recorded run uploads them.
- **A Trial that isn't held out.** A Benchmark's held-out Tasks are kept back for
  confirmation, so their Trials can't be forked.

Limits count the whole episode, so a fork after step 4 of a 10-turn limit has 6
turns left. Rewards and metric points from the first *k* steps are copied to the
fork and marked inherited; Verifiers reward and measure only the new steps.

Test that an Environment restores exactly with `assert_restorable`:

```python
from plural.testing import assert_restorable

assert_restorable(
    environment,
    task,
    [("guess", {"word": "crane"}), ("guess", {"word": "slate"})],
)
```

It runs the actions once, then restores at every step and replays the rest,
checking that every observation and every App's final State match byte for byte.
