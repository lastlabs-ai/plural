---
route: /docs/tutorials/shopkeeper
title: Shopkeeper
order: 117
description: Run a corner shop for a season, an episode with no final answer, and evaluate it by a running metric, cash on hand after every action, charted over the season and gated by a Verifier metric.
audience: all
nav: true
nav_group: Tutorials
outcome: You can measure an Agent after every action with a running metric, rank a Benchmark by it, and gate Trials on a metric when there is no answer to check.
---
# Shopkeeper

In this tutorial an Agent runs a corner shop for a season. Each day it reads the books,
buys stock, sets prices, and opens the shop. Customers buy what is on the shelf, and the
rent comes due at the end of the day.

There is no final answer to grade. What matters is how the shop's cash moves over the
whole season, and that it never goes below zero, not even for a moment after a big
delivery. That calls for a **running metric**: a measurement taken after every action,
not just at the end.

By the end you will have:

- measured the shop's cash after every action, and seen it charted over the season,
- ranked a Benchmark by that running metric instead of the score,
- gated each Trial on a [metric](../project/verifiers.md#gates-and-targets), with no answer to read.

## Before you start

You need Plural installed; see [Install](../getting-started.md#1-install). The project is
`examples/shopkeeper` in the [Plural repository](https://github.com/lastlabs-ai/plural):

```bash
git clone https://github.com/lastlabs-ai/plural.git
cp -R plural/examples/shopkeeper shopkeeper
cd shopkeeper
```

## What is in the project

| Concept | In this project |
| --- | --- |
| **App** | `Shop`: the shelf, the prices, the cash, and the books, on its State |
| **Environment** | `shop`: the App, a local Runtime, and a 200-action limit |
| **Task** | `shop-001` to `shop-003`: three seasons, with different cash, rent, and customers |
| **Verifier** | `shop-books`: measures cash after every action, scores the season, and gates on never going below zero |
| **Agent** | `shopkeeper-bot`: a model and its instructions |
| **Benchmark** | `shopkeeper`: the three seasons, ranked by cash at the end |

The Agent has four actions: `books` to read the books, `buy` to stock an item, `set_price`
to change a price, and `wait` to open for one day. A purchase is paid at once, so buying
too much on a thin day can put the shop below zero before a single customer arrives.

## Measure after every action

The Verifier declares two metrics in `verifiers/shop-books/verifier.yaml`:

```yaml
measure: verify.py:measure
metrics:
  - name: cash_on_hand
    kind: running
    unit: USD
    aggregate: final
    target: ">= 400"
  - name: never_negative_cash
    kind: binary
    gate: true
```

`measure` runs after every action, in the App host, beside the Verifier's other hooks.
It reads the shop's State and returns the cash:

```python
def measure(step: Step) -> dict[str, float]:
    books = step.current_state or {}
    return {"cash_on_hand": float(books["cash"])} if "cash" in books else {}
```

Each value is a point in the Trial's metric series. `aggregate: final` makes the Trial's
`cash_on_hand` the cash at the end of the season. These points are measurements: they
never enter the reward ledger, and the Agent never sees them.

The shop runs its own calendar, so it reports the day as its simulated time:

```python
def sim_time(self) -> float:
    return float(self.state.day)
```

Each point records the day beside the step, and the chart can use either axis.

## Score the path, not just the end

`check` runs once, when the season is over. It reads the State, and the whole cash
series as `episode.metric_series`:

```python
def check(episode: Episode) -> VerifierOutput:
    books = episode.state
    start = float(episode.expected["starting_cash"])
    target = float(episode.expected["target_profit"])
    solvent = float(books["lowest_cash"]) >= 0
    profit = float(books["cash"]) - start
    score = 0.0 if not solvent else min(1.0, max(0.0, profit / target))
    return VerifierOutput(score=score, metrics={"never_negative_cash": float(solvent)})
```

A shop that ever went below zero scores 0, however much cash it ended with. Nothing here
reads `episode.answer`: the Agent never gives one, and doesn't need to.

## Gate on a metric

`never_negative_cash` is a **gate**: a Trial passes only when every gate that applies to
it passes, so a season that dipped below zero fails, whatever its cash. `cash_on_hand`
has a `target` of `">= 400"`, which is reported as met or not and never decides a pass.

The Benchmark ranks on the running metric instead of the score:

```yaml
primary_metric: cash_on_hand
```

## Check the Tasks

`environments/shop/reference.py` is a cautious shopkeeper who stocks a little under an
ordinary day's demand and keeps cash back for the rent. Check that it can win every
season, and that an Agent that does nothing can't:

```bash
plural benchmark validate shopkeeper
```

This calls no model. It also reports the trust the default Runtime would give.

## Run it

Running the Agent calls a model, so it needs a Plural account. A season is around 70
actions, so look at the plan first:

```bash
plural run -b shopkeeper -a shopkeeper-bot --dry-run
plural run -b shopkeeper -a shopkeeper-bot --record
```

The summary ranks by `cash_on_hand` and shows the pass rate: the share of Trials that
passed every gate. With `--record`, open the Job in the hosted project:

- The Job's **Overview** has a metric selector: the mean of any metric, how many Trials
  it covers, and the pass rate.
- Each Trial's **Metrics** tab charts `cash_on_hand` over the season, step by step.
- The Benchmark's leaderboard can rank by any metric its Verifiers declare.

## Where to go next

- [Verifiers](../project/verifiers.md#measure-while-the-episode-runs): every running
  metric aggregate.
- [Gates and targets](../project/verifiers.md#gates-and-targets): what passes, and how
  the pass rate differs from the success rate.
