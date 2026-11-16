"""A corner shop as a Plural App: buy stock, set prices, and open for a day at a time.

The Agent runs the shop for a fixed number of days. Each ``wait`` opens the shop
for one day: seeded customers arrive, buy what is on the shelf at the price on
the tag, and the rent comes due. There is no final answer to check; what counts
is the cash at the end, and that it never went below zero on the way.
"""

import math
from typing import Annotated

from pydantic import Field

from plural import App, State, action, initial

WHOLESALE = {"coffee": 2.10, "bagel": 0.90, "juice": 1.60}
"""What the supplier charges per unit, in USD."""
LIST_PRICE = {"coffee": 3.50, "bagel": 2.00, "juice": 3.00}
"""What customers expect to pay; demand falls off as a price rises above it."""
BASE_DEMAND = {"coffee": 28.0, "bagel": 18.0, "juice": 10.0}
"""Customers who want each item on an ordinary day at the list price."""


class ShopState(State):
    """The shop's books. A Task may set the starting cash, the horizon, and the market."""

    days: int = initial(14, description="Days the shop runs before the episode ends.")
    cash: float = initial(150.0, description="Cash on hand at the start, in USD.")
    rent: float = initial(25.0, description="Rent due at the end of each day, in USD.")
    wholesale: dict[str, float] = initial(
        default_factory=lambda: dict(WHOLESALE),
        description="Supplier price per unit for each item, in USD.",
    )
    list_price: dict[str, float] = initial(
        default_factory=lambda: dict(LIST_PRICE),
        description="The price customers expect for each item, in USD.",
    )
    base_demand: dict[str, float] = initial(
        default_factory=lambda: dict(BASE_DEMAND),
        description="Customers who want each item on an ordinary day at the list price.",
    )
    elasticity: float = initial(
        1.6, description="How sharply demand falls as a price rises above the list price."
    )
    day: int = 1
    inventory: dict[str, int] = Field(default_factory=dict)
    prices: dict[str, float] = Field(default_factory=dict)
    lowest_cash: float = 150.0
    history: list[dict[str, float]] = Field(default_factory=list)
    """One entry per day the shop opened: revenue, units sold, and cash at close."""


def _poisson(rng, mean: float) -> int:
    """Draw one Poisson count with the App's seeded generator (Knuth's method)."""
    if mean <= 0:
        return 0
    limit, count, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


class Shop(App[ShopState]):
    """Run a corner shop: buy stock from the supplier, price it, and open for the day."""

    def reset(self, state):
        observation = super().reset(state)
        self.state.prices = dict(self.state.list_price) | dict(self.state.prices)
        self.state.lowest_cash = self.state.cash
        return observation

    def _item(self, item: str) -> str:
        if item not in self.state.wholesale:
            sold = ", ".join(sorted(self.state.wholesale))
            raise ValueError(f"The shop does not sell {item!r}. Items: {sold}.")
        return item

    def _open(self) -> None:
        if self.state.day > self.state.days:
            raise ValueError("The season is over; the shop is closed.")

    @action(read_only=True)
    def books(self) -> str:
        """Today's day, cash, stock on the shelf, shelf prices, supplier prices, and yesterday's sales."""
        state = self.state
        lines = [
            f"Day {min(state.day, state.days)} of {state.days}. Cash ${state.cash:,.2f}. "
            f"Rent ${state.rent:,.2f} is due at the end of each day.",
        ]
        for item in sorted(state.wholesale):
            lines.append(
                f"{item}: {state.inventory.get(item, 0)} on the shelf, priced "
                f"${state.prices.get(item, 0):,.2f}; supplier charges ${state.wholesale[item]:,.2f}."
            )
        if state.history:
            last = state.history[-1]
            lines.append(
                f"Yesterday: revenue ${last['revenue']:,.2f}, "
                + ", ".join(f"{item} sold {int(last.get(item, 0))}" for item in sorted(state.wholesale))
                + "."
            )
        return "\n".join(lines)

    @action
    def buy(self, item: str, units: Annotated[int, Field(gt=0, le=500)]) -> str:
        """Buy units of an item from the supplier, paid from cash now. Cash can go negative."""
        self._open()
        cost = round(self.state.wholesale[self._item(item)] * units, 2)
        self.state.cash = round(self.state.cash - cost, 2)
        self.state.inventory[item] = self.state.inventory.get(item, 0) + units
        self.state.lowest_cash = min(self.state.lowest_cash, self.state.cash)
        warning = " Cash is below zero: the shop is overdrawn." if self.state.cash < 0 else ""
        return f"Bought {units} {item} for ${cost:,.2f}. Cash ${self.state.cash:,.2f}.{warning}"

    @action
    def set_price(self, item: str, price: Annotated[float, Field(gt=0, le=100)]) -> str:
        """Set the shelf price of an item, in USD. It applies from the next day the shop opens."""
        self._open()
        self.state.prices[self._item(item)] = round(price, 2)
        return f"{item} now priced ${price:,.2f}."

    @action
    def wait(self) -> str:
        """Open the shop for one day: customers buy what is on the shelf, then rent is paid."""
        self._open()
        state = self.state
        sold: dict[str, float] = {}
        revenue = 0.0
        for item in sorted(state.wholesale):
            price = state.prices.get(item, state.list_price[item])
            ratio = price / state.list_price[item]
            mean = state.base_demand[item] * math.exp(-state.elasticity * (ratio - 1))
            wanted = _poisson(self.rng, mean)
            units = min(wanted, state.inventory.get(item, 0))
            state.inventory[item] = state.inventory.get(item, 0) - units
            sold[item] = float(units)
            revenue += units * price
        state.cash = round(state.cash + revenue - state.rent, 2)
        state.lowest_cash = min(state.lowest_cash, state.cash)
        state.history.append({"day": float(state.day), "revenue": round(revenue, 2), **sold,
                              "cash": state.cash})
        state.day += 1
        ending = (
            " The season is over."
            if state.day > state.days
            else f" Day {state.day} of {state.days} begins."
        )
        return (
            f"Sold "
            + ", ".join(f"{int(units)} {item}" for item, units in sold.items())
            + f" for ${revenue:,.2f}; paid ${state.rent:,.2f} rent. Cash ${state.cash:,.2f}."
            + ending
        )

    def sim_time(self) -> float:
        return float(self.state.day)

    def terminated(self) -> bool:
        return self.state.day > self.state.days
