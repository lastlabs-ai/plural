"""One item, two sides, alternating offers: a buyer and a seller haggle over a price.

The App deals each seat a private number: the buyer's value, the most the item
is worth to it, and the seller's cost, the least it can take. Neither sees the
other's. ``seat_1`` buys and ``seat_2`` sells; a Benchmark rotates who sits
where, so every Agent plays both sides. A deal at price P gives the buyer
``value - P`` and the seller ``P - cost``; no deal gives both nothing.
"""

from typing import Annotated, Any

from pydantic import Field

from plural import App, State, action, initial

ROLES = {"seat_1": "buyer", "seat_2": "seller"}


class DealState(State):
    """The item, each side's private number, and the offers so far."""

    item: str = initial("a used road bike", description="What is for sale.")
    value_range: tuple[float, float] = initial(
        (500.0, 700.0), description="The buyer's private value is drawn from this range, in USD."
    )
    cost_range: tuple[float, float] = initial(
        (300.0, 450.0), description="The seller's private cost is drawn from this range, in USD."
    )
    max_offers: int = initial(10, description="Offers allowed in all before talks fail.")
    value: float = 0.0
    cost: float = 0.0
    offers: list[dict[str, Any]] = Field(default_factory=list)
    to_move: str = "seat_2"
    price: float | None = None
    """The agreed price, once one side accepts the other's offer."""
    ended: str | None = None
    """``deal``, ``walked``, or ``out_of_offers``."""


class Market(App[DealState]):
    """Haggle over one item: offer a price, accept the other side's, or walk away."""

    name = "market"

    def reset(self, state: Any) -> Any:
        observation = super().reset(state)
        low, high = self.state.value_range
        self.state.value = round(self.rng.uniform(low, high), 0)
        low, high = self.state.cost_range
        self.state.cost = round(self.rng.uniform(low, high), 0)
        return observation

    def _role(self) -> str:
        return ROLES[str(self.seat)]

    def _open(self) -> None:
        if self.state.ended is not None:
            raise ValueError("The talks are over.")

    @action
    def offer(self, price: Annotated[float, Field(gt=0, le=100000)], message: str = "") -> str:
        """Offer a price in USD, with an optional message to the other side. Then it's their move."""
        self._open()
        self.state.offers = [
            *self.state.offers,
            {"by": self._role(), "price": round(price, 2), "message": message[:500]},
        ]
        self.state.to_move = "seat_1" if self.seat == "seat_2" else "seat_2"
        if len(self.state.offers) >= self.state.max_offers:
            self.state.ended = "out_of_offers"
            return f"You offered ${price:,.2f}. That was the last offer allowed: no deal."
        return f"You offered ${price:,.2f}."

    @action
    def accept(self) -> str:
        """Accept the other side's latest offer. The deal closes at that price."""
        self._open()
        theirs = [item for item in self.state.offers if item["by"] != self._role()]
        if not theirs or self.state.offers[-1]["by"] == self._role():
            return "There is no offer from the other side to accept yet."
        self.state.price = float(theirs[-1]["price"])
        self.state.ended = "deal"
        return f"Deal at ${self.state.price:,.2f}."

    @action
    def walk_away(self) -> str:
        """End the talks with no deal."""
        self._open()
        self.state.ended = "walked"
        return "You walked away. No deal."

    def turn(self) -> str:
        return self.state.to_move

    def observe(self, seat: str) -> dict[str, Any]:
        role = ROLES[seat]
        state = self.state
        private = (
            f"The item is worth ${state.value:,.0f} to you; paying more loses money."
            if role == "buyer"
            else f"The item cost you ${state.cost:,.0f}; selling for less loses money."
        )
        lines = [f"You are the {role} of {state.item}. {private}"]
        for item in state.offers:
            who = "You" if item["by"] == role else "They"
            note = f' ("{item["message"]}")' if item["message"] else ""
            lines.append(f"{who} offered ${item['price']:,.2f}{note}.")
        left = state.max_offers - len(state.offers)
        if state.ended == "deal":
            lines.append(f"Deal closed at ${state.price:,.2f}.")
        elif state.ended:
            lines.append("The talks ended with no deal.")
        else:
            lines.append(f"{left} offers left between you.")
        return {"text": "\n".join(lines)}

    def terminated(self) -> bool:
        return self.state.ended is not None
