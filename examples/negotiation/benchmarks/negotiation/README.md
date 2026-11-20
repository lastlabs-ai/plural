# negotiation

Two haggling Tasks, a road bike and a camera, each with a buyer in `seat_1` and a seller
in `seat_2`. Every evaluated Agent plays each Task twice, once from each seat
(`seatings: rotate`), against `steady-haggler`, a fixed opponent that follows a
concession schedule and calls no model. Fixing the opponent keeps scores comparable
from run to run.

It ranks on `surplus_usd`, the evaluated Agent's own surplus in dollars at the end of
each game, averaged over the seats it played. The score is the Agent's share of what
the deal could make, the buyer's value less the seller's cost. Results break both down
by seat, so an Agent that only does well as the buyer shows it.
