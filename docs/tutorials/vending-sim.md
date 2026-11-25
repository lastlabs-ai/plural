---
route: /docs/tutorials/vending-sim
title: Vending machine for a year
order: 118
description: Run a vending business for 365 simulated days, a long episode with a clock, simulated suppliers, and a context policy, then detach it, resume it after a crash, and find why an Agent stopped reordering.
audience: all
nav: true
nav_group: Tutorials
outcome: You can give an Environment simulated time, keep a long episode within an Agent's context, run it detached and resume it, and have the Inspector find a cause that only shows up months in.
---
# Vending machine for a year

In this tutorial an Agent runs a vending machine for a simulated year. Each day it checks
the machine and storage, restocks, orders from wholesalers, and waits for the day to
close. Customers buy what is in the machine, the location fee comes out of the bank, and
deliveries land in storage when they are due. Nothing happens unless the Agent waits, and
nothing ends until day 365.

A year is about 1,500 actions, far more than fits in one context, and longer than you
want to keep a laptop awake for. By the end you will have:

- given an Environment a [clock](../project/environments.md#simulated-time), so the
  world moves on its own between the Agent's actions,
- simulated the suppliers with [personas](../project/environments.md#simulated-people),
  billed apart from the Agent,
- kept a year within the Agent's context with a
  [context policy](../project/agents.md#keep-a-long-episode-in-context),
- charted net worth once a simulated day with a running metric,
- run the year detached, killed a run partway, and resumed it,
- had the Inspector find why one Agent ran out of stock, and test it with a fork.

## Before you start

You need Plural installed; see [Install](../getting-started.md#1-install). The project is
`examples/vending-sim` in the [Plural repository](https://github.com/lastlabs-ai/plural):

```bash
git clone https://github.com/lastlabs-ai/plural.git
cp -R plural/examples/vending-sim vending-sim
cd vending-sim
```

## What is in the project

```text
vending-sim/
  environments/vending/  four Apps on one clock: machine, storage, bank, suppliers
  tasks/vend-year/       365 days, with the supplier accounts in the instructions
  tasks/vend-quarter/    the first 90 days, to investigate cheaply
  tasks/vend-quarter-s1/ .. -s3/  the quarter from other weekdays: dev seeds
  tasks/vend-quarter-h1/ .. -h10/ ten more, held out for confirmation
  benchmarks/vending-quarter/     the fourteen quarters, ranked on net worth in dollars
  verifiers/vending-books/  net worth once a day, profit, and two gates
  agents/vending-luna/   a small model with a context policy
  agents/vending-rules/  a Harness that restocks by rule and calls no model
```

## A world with a clock

The Environment gives its Apps one clock, counting days, and ends the episode at a
horizon:

```yaml
clock:
  unit: day
  start: 1
horizon:
  sim_time: 365
autonomous: true
checkpoint_every:
  sim_time: 7
```

With a clock the Agent gets a `wait` action. Waiting runs the world to the next thing
that happens, here the day's close, and returns what happened meanwhile: what sold, the
fee, and any delivery. The machine App books that close with `self.schedule(...)` and
applies it in `advance(until)`; see [Simulated time](../project/environments.md#simulated-time)
for the hooks. `autonomous: true` means the Agent can't call `finish`, so the episode
always runs to the horizon and ends with `stop_reason: horizon_reached`.

## Suppliers who answer email

The suppliers App lets the Agent email each wholesaler. The answers come from personas:
small models, each told its own prices and terms.

```python
class Suppliers(App[SuppliersState]):
    personas = {supplier: _persona(supplier) for supplier in SUPPLIERS}

    @action
    def email(self, supplier: str, message: str) -> str:
        """Email a supplier, by its account name, and read its reply."""
        thread = self.state.threads.get(self._supplier(supplier), [])
        reply = self.personas[supplier].reply(self, message, history=thread[-6:])
        ...
```

What the personas cost is the Environment's cost. The Trial page shows it as
*Simulated people*, outside the Agent's total, so a chatty Agent isn't charged for its
suppliers' replies. Each answer is recorded in the Trial, so a fork replays it rather than
asking the model again.

## Net worth, once a day

The Verifier measures net worth, cash plus stock at book value, once a simulated day
rather than after every action:

```yaml
measure:
  python: verify.py:measure
  every:
    sim_time: 1
metrics:
  - name: net_worth_usd
    kind: running
    direction: higher
    unit: USD
    aggregate: final
  - name: profitable_by_day_60
    kind: binary
    gate: true
  - name: stockout_days
    kind: number
    direction: lower
    gate: true
    target: "<= 10"
```

A year is then 365 points however many actions the Agent takes, and the Trial page
charts them against the day. A Trial passes when it is profitable by day 60 and sells out
on no more than ten days.

## A year in context

`vending-luna` runs on a small model with a context policy:

```yaml
harness_config:
  context:
    strategy: summarize
    max_tokens: 20000
    keep_last_turns: 6
    summary_instructions: >
      Reply with exactly three lines and nothing else. "Machine:" and the units of each
      product in the machine. "Storage:" and the units of each product in storage and on
      order. "Bank:" and the cash in the bank.
```

Once the conversation passes 20,000 tokens, all but the last six turns are replaced by a
summary. The summary instructions are deliberately thin: they keep the day's numbers and
lose the Task's standing orders, supplier accounts included. You will find that with the
Inspector below.

## Run a quarter

Start with the 90-day Task:

```bash
plural run -t vend-quarter -a vending-luna --budget-usd 2
```

Open the Trial with `plural trial show TRIAL_ID` or on the Trial page. The chart shows
net worth by day; the episode lists each `context.compaction` where it happened.

## Rank on dollars

A score between 0 and 1 says whether the quarter reached its profit target; it can't
say that one Agent made twice the money. The `vending-quarter` Benchmark ranks on the
dollar metric instead:

```yaml
primary_metric: net_worth_usd
heldout:
  - vend-quarter-h1
  - vend-quarter-h2
  # … through vend-quarter-h10
```

Its Tasks are the quarter on fourteen seeds. Day 1 falls on a different weekday in the
first seven, so the quiet weekends land elsewhere and the customers come in a different
order; the rest also set the machine's `customers`, which draws another run of
customers on the same weekdays. Run the four dev seeds, once per Agent:

```bash
plural run --benchmark vending-quarter -a vending-rules --budget-usd 1 --record
plural run --benchmark vending-quarter -a vending-luna --budget-usd 4 --record
```

The run summary and `plural job report` give net worth in dollars, and the
Benchmark's leaderboard ranks the two on it, higher first, with the score beside it. The ten `-h` seeds are held
out: a plain run leaves them alone. Ten, because a paired verdict needs ten shared
Tasks; `plural benchmark validate` warns about a Benchmark that holds out fewer.

## Run the year detached

A whole year takes hours. `--detach` runs it in a Daytona sandbox and returns:

```bash
plural run -t vend-year -a vending-rules --budget-usd 1 --detach
plural job show JOB_ID
```

`vending-rules` calls no model, so it plays a year in minutes at no cost. The detached
run records the Job in your hosted project as it goes, with a key minted for that Job
alone; see [Long runs](../running/jobs.md#long-runs-detach-interrupt-and-resume).
`plural job show` copies the Job back as it goes and says how far it has got.

## Kill it, and resume

Run the year locally, and kill the process partway, after day 140:

```bash
plural run -t vend-year -a vending-rules --budget-usd 1
# kill the run after day 140
plural job show JOB_ID         # names the interrupted Trial and where it can resume
plural trial resume TRIAL_ID
```

The resumed Trial restarts from the latest weekly checkpoint, with every App's State, its
random state, and the clock as they stood. With the same seed it finishes exactly as an
uninterrupted run does: the same actions, the same net worth every day, the same score.

## Find why an Agent ran dry

Run the quarter a few times with `vending-luna`. Some Trials fail the `stockout_days`
gate: partway through, the Agent stops reordering, and the machine runs dry. Ask the
Inspector why:

```bash
plural job inspect JOB_ID --trial TRIAL_ID --budget-usd 2
```

The Inspector reads the episode, sees the Agent's errors start after the first
compaction, and reads what the summary dropped: the supplier accounts and standing
orders from the Task. It names the cause `context` and tests it with Forks from just
before that compaction, whose context policy has summary instructions that keep the
accounts and orders, against control Forks that change nothing. If the changed Forks
pass more often than the controls, the Finding is `confirmed`.

The fix is a new revision of the Agent with that policy: `plural agent revise` applies
it. Investigate on the dev seeds only. Run them again with the new revision, and
compare the two Jobs:

```bash
plural run --benchmark vending-quarter -a vending-luna --budget-usd 4
plural job report NEW_JOB_ID --compare OLD_JOB_ID
```

The comparison pairs the Jobs Task by Task, in pass rate, success rate, and net worth
in dollars, higher better, each with a 95% interval. Then confirm the revision once on
seeds it was never tuned against:

```bash
plural run --benchmark vending-quarter --heldout -a vending-luna --budget-usd 3
```

Running the held-out seeds is counted as a peek.

## Next

- [Simulated time](../project/environments.md#simulated-time) and
  [checkpoints](../project/environments.md#checkpoints-and-resume), in full.
- [The Inspector](../running/inspector.md), and how it tests a cause with Forks.
- [Negotiation](negotiation.md): several Agents in one episode.
