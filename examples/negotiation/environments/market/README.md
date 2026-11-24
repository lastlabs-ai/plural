# market

One App, `market`, that two Agents share. `seat_1` buys and `seat_2` sells.

- `offer(price, message)` puts a price on the table, with an optional note, and hands
  the move to the other side.
- `accept()` takes the other side's latest offer; the deal closes at that price.
- `walk_away()` ends the talks with no deal.

Each seat's view (`observe`) shows its own private number and the offers so far. The
seller moves first. Talks fail after `max_offers` offers in all.

A deal at price P gives the buyer `value - P` and the seller `P - cost`, its
**surplus**. No deal gives both nothing.
