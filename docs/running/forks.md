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

Use `--checkpoint NAME` instead of `--step` to fork from a saved checkpoint, and
`--json` for the full result. `--record` records the fork Job in your hosted
project, where each fork Trial shows where it started and the original Trial lists
its forks.

### Fork from the web app

On a finished Trial's page, **Fork from here** builds the command for you. Run it
in the project folder that recorded the Trial: a fork needs the Trial's local
record. When you name a recorded Trial by its hosted id, Plural finds the local
Trial it came from.

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
| `oracle_tool` | `{name, description, answer}` | Offers one more tool that returns the answer you give. |

An oracle tool's answer is what you type in the payload. Plural never fills it in
from an App's State or a Task's answer key.

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
- **A local record.** The Trial's steps, App States, and workspace snapshots, which
  every local run keeps.
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
