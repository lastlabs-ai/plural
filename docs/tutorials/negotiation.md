---
route: /docs/tutorials/negotiation
title: Negotiation
order: 119
description: Rank an Agent at a game for two, haggling against a fixed opponent from both sides of the table, with each seat's surplus charted, then run a cooperative Task where it plays with itself.
audience: all
nav: true
nav_group: Tutorials
outcome: You can run a Benchmark whose Tasks several Agents share, with rotated seats, a fixed opponent, and per-seat running metrics, and a cooperative party Task in a Benchmark.
---
# Negotiation

In this tutorial two Agents haggle. A buyer and a seller take turns offering a price for
a used bike or a camera, until one accepts, one walks away, or the offers run out. Each
knows only its own number: what the item is worth to the buyer, or what it cost the
seller.

Ranking an Agent at a game like this needs care. Play it against a different opponent
each time and you measure the opponent; play it from one side only and you measure the
side. By the end you will have:

- run a Benchmark against one fixed opponent, from both seats in turn,
- charted each seat's surplus as the offers go back and forth,
- run a cooperative Task, where an Agent plays with a copy of itself, in a Benchmark.

## Before you start

You need Plural installed; see [Install](../getting-started.md#1-install). The market
seats each player as its own OS user, which needs Docker. The project is
`examples/negotiation` in the [Plural repository](https://github.com/lastlabs-ai/plural):

```bash
git clone https://github.com/lastlabs-ai/plural.git
cp -R plural/examples/negotiation negotiation
cd negotiation
```

## What is in the project

```text
negotiation/
  environments/market/   one App a buyer (seat_1) and a seller (seat_2) share
  environments/vault/    one App two partners share
  tasks/bike-deal/, tasks/camera-deal/   competitive, two players
  tasks/two-keys/        cooperative, two players
  verifiers/deal-books/  each seat's surplus after every offer, and a gate per seat
  agents/negotiator-luna/   the Agent being ranked, on a small model
  agents/steady-haggler/    the fixed opponent, a Harness that calls no model
  benchmarks/negotiation/, benchmarks/teamwork/
```

## A game for two

The market Environment has a party of exactly two, and seats them in isolation, so
neither can read the other's private number:

```yaml
party:
  min: 2
  max: 2
  isolation: isolated
```

A Benchmark ranks every Agent at the same game, so each Task pins its party size, and a
haggling Task says its seats compete:

```yaml
name: bike-deal
environment: market
verifiers:
  - deal-books
party_size: 2
competitive: true
```

## Each seat's surplus

The Verifier's `measure` hook returns a value per seat, after every offer:

```python
def measure(step: Step) -> dict[str, dict[str, float]]:
    """Each seat's surplus at the offer on the table, and whether its deal is fair."""
    state = step.apps["market"].state.model_dump()
    return {"surplus_usd": _surplus(state, _on_table(state)), "fair_deal": _fair(state)}
```

`_surplus` gives `{"seat_1": ..., "seat_2": ...}`: the buyer's value less the price, and
the price less the seller's cost. The Trial page charts one series per seat. Each Agent
is credited with its own seat's surplus, and `seat_aggregate: sum` makes the episode's
value both together, what the deal created.

## A gate per seat

Surplus says how well a seat did; the gate says whether it did its job at all. The
Verifier declares `fair_deal` as a gate measured per seat:

```yaml
- name: fair_deal
  kind: running
  aggregate: final
  seat_aggregate: min
  gate: true
  target: ">= 1"
```

A seat passes once a deal closes inside its own limit: the buyer at or under its value,
the seller at or over its cost. A walk-away or running out of offers fails both. Each
seat is judged on its own, so results show each Agent's pass rate from each seat, and
`seat_aggregate: min` passes the Trial only when both sides did.

## Rank against a fixed opponent

The Benchmark names an opponent and rotates the seats:

```yaml
name: negotiation
tasks:
  - bike-deal
  - camera-deal
opponents:
  - steady-haggler@1.0.0
seatings: rotate
primary_metric: surplus_usd
```

The opponent fills every seat the ranked Agent doesn't, and is never ranked itself.
`seatings: rotate` plays each Task once from each seat, so every Agent buys and sells
against the same haggler. A competitive Task in a Benchmark with no opponents is
refused: the ranked Agents would only be playing each other.

```bash
plural run -b negotiation -a negotiator-luna --budget-usd 0.5
```

The summary gives each Agent's results overall and from each seat:

```text
  negotiator-luna: surplus_usd … score … over 2 Tasks
    as seat_1: score …, surplus_usd … (2 Trials)
    as seat_2: score …, surplus_usd … (2 Trials)
  steady-haggler: … fixed opponent: …
```

## Play together

The vault Task is cooperative. Each partner knows two digits of a four-digit code, and
they open the vault by sharing what they know on a board they both read. Its Task pins
two players and isn't competitive, so a Benchmark with no opponents seats the ranked
Agent in both seats:

```bash
plural run -b teamwork -a negotiator-luna --budget-usd 0.5
```

The vault's party is `isolation: shared`: the partners run as one OS user, which the
`local` Runtime can give. A Benchmark refuses a competitive Task whose seats are shared,
since each seat could read and act for its rival.

## Next

- [Several agents](../project/multi-agent.md), in full: parties, seats, and isolation.
- [Measure while the episode runs](../project/verifiers.md#measure-while-the-episode-runs).
- [Vending machine for a year](vending-sim.md): a long episode with simulated time.
