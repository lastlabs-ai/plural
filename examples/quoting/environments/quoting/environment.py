"""A steel mill's quoting desk as a Plural App. State holds the mill's truth; actions read it."""

import math
from datetime import date, timedelta
from typing import Annotated

from pydantic import BaseModel, Field

from plural import App, State, action, initial

PRICE_BOOK = {
    "A36": 1140.00,
    "A572-50": 1225.00,
    "A516-70": 1390.00,
    "A500-B": 1310.00,
    "1018": 1275.00,
    "304SS": 3450.00,
}
COSTS = {
    "A36": 905.00,
    "A572-50": 960.00,
    "A516-70": 1100.00,
    "A500-B": 1020.00,
    "1018": 990.00,
    "304SS": 2900.00,
}
STOCK = {
    "A36": 400.0,
    "A572-50": 250.0,
    "A516-70": 120.0,
    "A500-B": 180.0,
    "1018": 90.0,
    "304SS": 40.0,
}


class Quote(BaseModel):
    """A quote as it went to the customer, with the earliest date the mill could deliver."""

    grade: str
    tons: float
    price_per_ton: float
    total_price: float
    delivery_date: str
    notes: str
    earliest_delivery: str


class MillState(State):
    """The mill's facts, which a Task may set, and what the Agent did with them."""

    today: str = initial("2026-12-01", description="The day the request arrives (ISO date).")
    price_book: dict[str, float] = initial(
        default_factory=lambda: dict(PRICE_BOOK),
        description="List price per short ton for each grade the mill sells, in USD.",
    )
    costs: dict[str, float] = initial(
        default_factory=lambda: dict(COSTS),
        description="The mill's cost per short ton for each grade, in USD.",
    )
    stock: dict[str, float] = initial(
        default_factory=lambda: dict(STOCK),
        description="Short tons on hand for each grade.",
    )
    booked: list[str] = initial(
        default_factory=list,
        description="Days the mill is already booked and cannot roll new orders (ISO dates).",
    )
    tons_per_day: float = initial(25.0, description="Short tons the mill rolls in one free day.")
    market_move: float = initial(
        0.01, description="Largest fraction the market price moves from list on each lookup."
    )
    prices_given: dict[str, float] = Field(default_factory=dict)
    schedule_checked: bool = False
    quote: Quote | None = None
    handoff: str | None = None


def earliest_delivery(mill: MillState, tons: float) -> date:
    """The first day an order can arrive: after enough free mill days to roll it, plus one to ship."""
    needed = max(1, math.ceil(tons / mill.tons_per_day))
    booked = {date.fromisoformat(day) for day in mill.booked}
    day = date.fromisoformat(mill.today)
    while needed:
        day += timedelta(days=1)
        if day not in booked:
            needed -= 1
    return day + timedelta(days=1)


class Mill(App[MillState]):
    """Answer a customer's request for quote: look up prices, stock, and the mill schedule."""

    def _grade(self, grade: str) -> str:
        if grade not in self.state.price_book:
            stocked = ", ".join(sorted(self.state.price_book))
            raise ValueError(f"The mill does not sell {grade!r}. Grades it sells: {stocked}.")
        return grade

    def _open(self) -> None:
        if self.state.quote is not None or self.state.handoff is not None:
            raise ValueError("This request is already answered.")

    @action
    def lookup_price(self, grade: str) -> str:
        """Today's price per short ton for a grade. The market moves, so quote the latest figure."""
        list_price = self.state.price_book[self._grade(grade)]
        move = self.rng.uniform(-self.state.market_move, self.state.market_move)
        price = round(list_price * (1 + move), 2)
        self.state.prices_given[grade] = price
        return f"{grade}: ${price:,.2f} per short ton today."

    @action
    def check_stock(self, grade: str, tons: Annotated[float, Field(gt=0)]) -> str:
        """Whether the mill has enough of a grade on hand, in short tons."""
        on_hand = self.state.stock.get(self._grade(grade), 0.0)
        verdict = "enough" if on_hand >= tons else "not enough"
        return f"{on_hand:g} short tons of {grade} on hand: {verdict} for {tons:g}."

    @action
    def check_schedule(self, tons: Annotated[float, Field(gt=0)]) -> str:
        """Optional: view mill bookings."""
        self.state.schedule_checked = True
        when = earliest_delivery(self.state, tons)
        return f"Earliest delivery for {tons:g} short tons: {when.isoformat()}."

    @action
    def submit_quote(
        self,
        grade: str,
        tons: Annotated[float, Field(gt=0)],
        price_per_ton: Annotated[float, Field(gt=0)],
        total_price: Annotated[float, Field(gt=0)],
        delivery_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")],
        notes: str,
    ) -> str:
        """Send the customer one quote. Prices in USD per short ton; delivery as YYYY-MM-DD."""
        self._open()
        self._grade(grade)
        date.fromisoformat(delivery_date)
        self.state.quote = Quote(
            grade=grade,
            tons=tons,
            price_per_ton=price_per_ton,
            total_price=total_price,
            delivery_date=delivery_date,
            notes=notes,
            earliest_delivery=earliest_delivery(self.state, tons).isoformat(),
        )
        return "Quote sent to the customer."

    @action
    def handoff(self, reason: str) -> str:
        """Pass the request to a person, with the reason, when it can't be quoted safely."""
        self._open()
        self.state.handoff = reason
        return "Handed to the sales team."

    def terminated(self) -> bool:
        return self.state.quote is not None or self.state.handoff is not None
