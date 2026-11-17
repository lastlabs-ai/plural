# Shop

A corner shop that sells coffee, bagels, and juice. The Agent runs it for a season of
days. There is no question to answer: what counts is how much cash the shop has at the
end, and that it never went below zero along the way.

## Actions

| Action | What it does |
| --- | --- |
| `books()` | The day, cash, stock and shelf price of each item, the supplier's price, and yesterday's sales. Read-only. |
| `buy(item, units)` | Buys stock from the supplier, paid from cash at once. Cash can go below zero. |
| `set_price(item, price)` | Sets an item's shelf price from the next day the shop opens. |
| `wait()` | Opens the shop for one day. Customers buy what is on the shelf at the shelf price, then rent is paid. After the last day the episode ends. |

## Customers

Each day, the customers who want an item are a Poisson draw from the episode's seed. On
an ordinary day at the list price, about 28 want coffee, 18 a bagel, and 10 a juice.
Demand falls off exponentially as a price rises above the list price, set by
`elasticity`. A customer who finds the shelf empty buys nothing, and unsold stock keeps.

## State

A Task may set `days`, `cash`, `rent`, `wholesale`, `list_price`, `base_demand`, and
`elasticity`. The shop records `day`, `inventory`, `prices`, `lowest_cash` (the lowest
cash reached, including after a purchase within the day), and `history`, one entry per
day it opened.

The App keeps a clock: `sim_time()` returns the day, so running metrics chart against
the shop's days as well as against steps.
