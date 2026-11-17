# Quoting

A steel mill's quoting desk. Each Task is one customer's request for quote (RFQ). The
Agent answers it with one quote, or hands it to a person when it can't be quoted safely.

## Actions

| Action | What it does |
| --- | --- |
| `lookup_price(grade)` | Today's price per short ton. It moves up to 1% from list on each lookup, drawn from the episode's seed. |
| `check_stock(grade, tons)` | Tons on hand, and whether that covers the order. |
| `check_schedule(tons)` | The earliest delivery date the mill can meet for that tonnage. |
| `submit_quote(grade, tons, price_per_ton, total_price, delivery_date, notes)` | Sends the quote and ends the episode. `notes` is the message to the customer. |
| `handoff(reason)` | Passes the request to the sales team and ends the episode. |

A grade the mill doesn't sell is refused, and the refusal lists the grades it does sell.

## State

The mill's facts are fields a Task may set: `today`, `price_book` and `costs` (USD per
short ton), `stock` (short tons), `booked` (days the mill can't roll new orders), and
`tons_per_day`. The defaults are a mill with six grades, plenty of stock, and an empty
schedule.

An order needs one free mill day for every 25 tons, starting the day after `today`, and
arrives the day after the last one. `check_schedule` and the recorded quote's
`earliest_delivery` both use that rule.

The episode's progress is recorded beside the facts: `prices_given` (the last price each
lookup returned, per grade), `schedule_checked`, and the `quote` or `handoff`. The Agent
never sees State. A Verifier does.

## Units

Prices and tonnage are in short tons (2,000 lb). Some customers order in
hundredweight (cwt, 100 lb): 20 cwt is one short ton.
