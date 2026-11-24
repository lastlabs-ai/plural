"""A vending machine run for a year, the sample for a long-running Agent.

Four Apps share a clock that counts days. The machine is what customers buy
from; storage is the room behind it; the bank holds the cash; the suppliers
take email and orders. Every day ends on its own, with or without the Agent:
the machine sells what is in it, the location fee is paid, and orders that are
due arrive in storage. The Agent's job is to keep the machine stocked and
priced, and storage supplied, for as long as the year lasts.
"""

import math
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import Field

from plural import App, State, action, initial
from plural.sim import Persona

PRODUCTS = ("candy", "chips", "soda", "water")
LIST_PRICE = {"candy": 1.50, "chips": 1.75, "soda": 2.00, "water": 1.25}
"""What customers expect to pay; demand falls off as a price rises above it."""
BASE_DEMAND = {"candy": 5.0, "chips": 7.0, "soda": 9.0, "water": 6.0}
"""Customers who want each product on an ordinary weekday at the list price."""
SLOT_CAPACITY = 40
APPS = ("machine", "storage", "bank", "suppliers")
SUPPLIERS: dict[str, dict[str, Any]] = {
    "harbor-wholesale": {
        "display": "Harbor Wholesale",
        "prices": {"candy": 0.70, "chips": 0.80, "soda": 0.90, "water": 0.55},
        "lead_days": 1,
        "minimum": 1,
    },
    "pinecrest-supply": {
        "display": "Pinecrest Supply",
        "prices": {"candy": 0.45, "chips": 0.55, "soda": 0.60, "water": 0.30},
        "lead_days": 3,
        "minimum": 50,
    },
}
"""Each supplier's unit prices in USD, days from order to delivery, and minimum units."""


def _poisson(rng: Any, mean: float) -> int:
    """Draw one Poisson count with an App's seeded generator (Knuth's method)."""
    if mean <= 0:
        return 0
    limit, count, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


def _product(name: str) -> str:
    if name not in PRODUCTS:
        raise ValueError(f"No product {name!r}. Products: {', '.join(PRODUCTS)}.")
    return name


def unit_value() -> dict[str, float]:
    """What a unit in stock is worth on the books: the lowest supplier price."""
    return {
        product: min(float(item["prices"][product]) for item in SUPPLIERS.values())
        for product in PRODUCTS
    }


def net_worth(apps: Mapping[str, Any]) -> float:
    """Cash, plus stock in the machine, in storage, and on order, at book value."""
    value = unit_value()
    machine = apps["machine"].state
    storage = apps["storage"].state
    suppliers = apps["suppliers"].state
    stock = sum(value[p] * (machine.slots.get(p, 0) + storage.units.get(p, 0)) for p in PRODUCTS)
    on_order = sum(float(order["cost"]) for order in suppliers.open_orders)
    return round(float(apps["bank"].state.cash) + stock + on_order, 2)


class MachineState(State):
    """The machine: what is in each slot, at what price, and how it sold."""

    days: int = initial(365, description="Days the machine runs before the episode ends.")
    fee: float = initial(16.0, description="Location fee paid at the end of each day, in USD.")
    slots: dict[str, int] = initial(
        default_factory=lambda: dict.fromkeys(PRODUCTS, 20),
        description="Units of each product in the machine at the start.",
    )
    elasticity: float = initial(
        1.8, description="How sharply demand falls as a price rises above the list price."
    )
    start_weekday: int = initial(
        0,
        minimum=0,
        maximum=6,
        description="The weekday of day 1, 0 for Monday. Weekends are quieter, so each "
        "start is a different run of customers.",
    )
    customers: int = initial(
        0,
        minimum=0,
        description="Which run of customers. Tasks that differ only here see different "
        "customers on the same days.",
    )
    prices: dict[str, float] = Field(default_factory=lambda: dict(LIST_PRICE))
    day: int = 1
    revenue_total: float = 0.0
    units_total: int = 0
    stockout_days: int = 0
    """Days on which at least one product sold out with customers still wanting it."""
    net_worth_day_60: float | None = None
    last_day: dict[str, Any] = Field(default_factory=dict)


class Machine(App[MachineState]):
    """The vending machine customers buy from. It closes out every day on its own."""

    name = "machine"

    def reset(self, state: Mapping[str, Any]) -> Any:
        observation = super().reset(state)
        if self.state.customers:
            self.rng.seed(f"{self.seed}:{self.name}:customers:{self.state.customers}")
        self.schedule(self.now + 1, "close")
        return observation

    @action(read_only=True)
    def machine_status(self) -> str:
        """Each product's units in the machine, its price, and yesterday's sales."""
        state = self.state
        lines = [f"Day {state.day} of {state.days}. Each slot holds {SLOT_CAPACITY} units."]
        for product in PRODUCTS:
            sold = state.last_day.get("sold", {}).get(product)
            lines.append(
                f"{product}: {state.slots.get(product, 0)} in the machine at "
                f"${state.prices[product]:.2f}"
                + (f"; sold {sold} yesterday" if sold is not None else "")
            )
        return "\n".join(lines)

    @action
    def set_price(self, product: str, price: Annotated[float, Field(gt=0, le=20)]) -> str:
        """Set a product's price in the machine, in USD. Customers see it from the next sale."""
        self.state.prices[_product(product)] = round(price, 2)
        return f"{product} is now ${price:.2f}."

    @action
    def restock(self, product: str, units: Annotated[int, Field(gt=0, le=SLOT_CAPACITY)]) -> str:
        """Move units of a product from storage into the machine, up to the slot's capacity."""
        storage = self.peer("storage").state
        room = SLOT_CAPACITY - self.state.slots.get(_product(product), 0)
        moved = min(units, room, storage.units.get(product, 0))
        if moved <= 0:
            reason = "the slot is full" if room <= 0 else "storage has none"
            return f"Moved no {product}: {reason}."
        storage.units[product] -= moved
        self.state.slots[product] = self.state.slots.get(product, 0) + moved
        return (
            f"Moved {moved} {product} into the machine ({self.state.slots[product]} now); "
            f"{storage.units[product]} left in storage."
        )

    def advance(self, until: float) -> Sequence[Any]:
        events = []
        for _ in self.due_events():
            events.append(self._close())
            if self.state.day <= self.state.days:
                self.schedule(self.now + 1, "close")
        return events

    def _close(self) -> str:
        state = self.state
        bank = self.peer("bank")
        weekday = (state.day - 1 + state.start_weekday) % 7
        season = 1 + 0.25 * math.sin(2 * math.pi * (state.day - 80) / 365)
        traffic = (0.6 if weekday >= 5 else 1.0) * season
        sold: dict[str, int] = {}
        revenue = 0.0
        short = False
        for product in PRODUCTS:
            ratio = state.prices[product] / LIST_PRICE[product]
            mean = BASE_DEMAND[product] * traffic * math.exp(-state.elasticity * (ratio - 1))
            wanted = _poisson(self.rng, mean)
            units = min(wanted, state.slots.get(product, 0))
            short = short or wanted > units
            state.slots[product] = state.slots.get(product, 0) - units
            sold[product] = units
            revenue += units * state.prices[product]
        revenue = round(revenue, 2)
        bank.deposit(revenue, f"Day {state.day} sales")
        bank.withdraw(state.fee, f"Day {state.day} location fee")
        state.revenue_total = round(state.revenue_total + revenue, 2)
        state.units_total += sum(sold.values())
        state.stockout_days += int(short)
        state.last_day = {"day": state.day, "sold": sold, "revenue": revenue}
        if state.day == 60:
            state.net_worth_day_60 = net_worth({name: self.peer(name) for name in APPS})
        empty = [product for product in PRODUCTS if state.slots.get(product, 0) == 0]
        state.day += 1
        return (
            f"Day {state.day - 1} closed: sold "
            + ", ".join(f"{units} {product}" for product, units in sold.items())
            + f" for ${revenue:.2f}; paid the ${state.fee:.2f} location fee."
            + (f" Sold out: {', '.join(empty)}." if empty else "")
        )

    def terminated(self) -> bool:
        return self.state.day > self.state.days


class StorageState(State):
    """The storage room behind the machine."""

    units: dict[str, int] = initial(
        default_factory=lambda: dict.fromkeys(PRODUCTS, 30),
        description="Units of each product in storage at the start.",
    )


class Storage(App[StorageState]):
    """The storage room. Deliveries arrive here, and restock takes from it."""

    name = "storage"

    @action(read_only=True)
    def storage_status(self) -> str:
        """Units of each product in storage, and what is on order and when it arrives."""
        orders = self.peer("suppliers").state.open_orders
        lines = [
            f"{product}: {self.state.units.get(product, 0)} in storage" for product in PRODUCTS
        ]
        lines += [
            f"On order: {order['units']} {order['product']}, arriving day {order['due']}"
            for order in orders
        ]
        return "\n".join(lines)

    def advance(self, until: float) -> Sequence[Any]:
        events = []
        suppliers = self.peer("suppliers").state
        for event in self.due_events():
            data = event["data"]
            self.state.units[data["product"]] = (
                self.state.units.get(data["product"], 0) + data["units"]
            )
            suppliers.open_orders = [
                order for order in suppliers.open_orders if order["order"] != data["order"]
            ]
            events.append(
                f"A delivery arrived: {data['units']} {data['product']} into storage "
                f"(order #{data['order']})."
            )
        return events


class BankState(State):
    """The machine's bank account."""

    cash: float = initial(300.0, description="Cash at the start, in USD.")
    lowest_cash: float = 300.0
    recent: list[str] = Field(default_factory=list)
    """The last ten transactions, newest last."""


class Bank(App[BankState]):
    """The bank account that sales go into and fees and orders come out of."""

    name = "bank"

    def reset(self, state: Mapping[str, Any]) -> Any:
        observation = super().reset(state)
        self.state.lowest_cash = self.state.cash
        return observation

    @action(read_only=True)
    def bank_balance(self) -> str:
        """The cash balance and the most recent transactions."""
        return "\n".join([f"Cash: ${self.state.cash:,.2f}", *self.state.recent[-5:]])

    def deposit(self, amount: float, memo: str) -> None:
        self._post(amount, memo)

    def withdraw(self, amount: float, memo: str) -> None:
        self._post(-amount, memo)

    def _post(self, amount: float, memo: str) -> None:
        self.state.cash = round(self.state.cash + amount, 2)
        self.state.lowest_cash = min(self.state.lowest_cash, self.state.cash)
        self.state.recent = [*self.state.recent, f"{memo}: {amount:+,.2f}"][-10:]


def _script(supplier: str) -> Any:
    """A supplier's answer without a model: its price list, terms, and a sign-off."""
    terms = SUPPLIERS[supplier]

    def answer(messages: Sequence[Mapping[str, str]]) -> str:
        prices = ", ".join(f"{p} ${terms['prices'][p]:.2f}" for p in PRODUCTS)
        return (
            f"Thanks for writing to {terms['display']}. Our unit prices are {prices}. "
            f"Orders arrive {terms['lead_days']} day(s) after you place them"
            + (f", with a minimum of {terms['minimum']} units." if terms["minimum"] > 1 else ".")
        )

    return answer


def _persona(supplier: str) -> Persona:
    terms = SUPPLIERS[supplier]
    prices = ", ".join(f"{p} ${terms['prices'][p]:.2f}" for p in PRODUCTS)
    return Persona(
        name=supplier,
        instructions=(
            f"You answer email for {terms['display']}, a snack wholesaler, in two or three "
            f"sentences. Unit prices: {prices}. Delivery takes {terms['lead_days']} day(s) "
            f"after an order. Minimum order: {terms['minimum']} units of a product. Prices are "
            "fixed and you never negotiate. Orders are placed with the order tool, not by email."
        ),
        script=_script(supplier),
    )


class SuppliersState(State):
    """Email threads with each supplier, and orders not yet delivered."""

    threads: dict[str, list[dict[str, str]]] = Field(default_factory=dict)
    open_orders: list[dict[str, Any]] = Field(default_factory=list)
    next_order: int = 1
    spent: dict[str, float] = Field(default_factory=dict)
    """What has been spent with each supplier, in USD."""


class Suppliers(App[SuppliersState]):
    """The wholesalers. Email one for prices and terms, and order stock into storage."""

    name = "suppliers"
    personas = {supplier: _persona(supplier) for supplier in SUPPLIERS}

    def _supplier(self, supplier: str) -> str:
        if supplier not in SUPPLIERS:
            raise ValueError(f"No supplier account {supplier!r}.")
        return supplier

    @action
    def email(self, supplier: str, message: str) -> str:
        """Email a supplier, by its account name, and read its reply."""
        thread = self.state.threads.get(self._supplier(supplier), [])
        reply = self.personas[supplier].reply(self, message, history=thread[-6:])
        self.state.threads[supplier] = [
            *thread,
            {"role": "user", "content": message},
            {"role": "assistant", "content": reply},
        ][-12:]
        return reply

    @action
    def order(
        self, supplier: str, product: str, units: Annotated[int, Field(gt=0, le=1000)]
    ) -> str:
        """Order units of a product from a supplier, by its account name. Paid from the bank now."""
        terms = SUPPLIERS[self._supplier(supplier)]
        if units < terms["minimum"]:
            return f"Declined: the minimum order is {terms['minimum']} units."
        cost = round(float(terms["prices"][_product(product)]) * units, 2)
        bank = self.peer("bank")
        if bank.state.cash < cost:
            return (
                f"Declined: the order costs ${cost:,.2f} and the bank has ${bank.state.cash:,.2f}."
            )
        number = self.state.next_order
        self.state.next_order += 1
        bank.withdraw(cost, f"Order #{number}")
        due = int(self.now) + int(terms["lead_days"])
        self.state.open_orders = [
            *self.state.open_orders,
            {"order": number, "product": product, "units": units, "cost": cost, "due": due},
        ]
        self.state.spent[supplier] = round(self.state.spent.get(supplier, 0.0) + cost, 2)
        # Time D is the start of day D: the delivery lands as day D - 1 closes.
        self.peer("storage").schedule(due, "delivery", product=product, units=units, order=number)
        return f"Order #{number}: {units} {product} for ${cost:,.2f}, arriving day {due}."


__all__ = ["Bank", "Machine", "Storage", "Suppliers", "net_worth", "unit_value"]
