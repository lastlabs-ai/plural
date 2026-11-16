# Shopkeeper

Three seasons at a corner shop: two weeks with ordinary customers, two weeks that start
short of cash, and three weeks with higher rent and customers who mind prices less.

The leaderboard ranks on `cash_on_hand`, the running metric `shop-books` samples after
every action: an Agent's value is the mean, across its Trials, of the cash at the end
of each season. The score is profit against each season's target, and is 0 for a shop
that ever went below zero cash, which `never_negative_cash` reports on its own.

There is no final answer: the Agent never has to say anything, and the books in State
are the whole result.
