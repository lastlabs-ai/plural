# vending-quarter

Ninety days running a vending machine, on seven seeds. Each seed starts day 1 on a
different weekday, so its quiet weekend days fall elsewhere and its customers come in
a different order.

The leaderboard ranks on `net_worth_usd`: the last day's cash plus the stock at book
value, in dollars, higher is better. Making twice the money ranks higher, which a
0-to-1 score could not show. The score, 1 when the quarter's profit reaches the Task's
target, is reported beside it, as are the two gates: profitable by day 60, and at most
ten days with a product sold out.

Four seeds are for development. Three, `vend-quarter-h1` to `-h3`, are held out: a
plain run leaves them out, and running them is counted as a reveal.
