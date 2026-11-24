"""Read the vending business's books: net worth each day, and the year's result."""

from collections.abc import Mapping
from typing import Any

from plural import Episode, Step, VerifierOutput

PRODUCTS = ("candy", "chips", "soda", "water")
UNIT_VALUE = {"candy": 0.45, "chips": 0.55, "soda": 0.60, "water": 0.30}
"""Book value of a unit in stock: the lowest supplier price."""


def _net_worth(states: Mapping[str, Any]) -> float:
    machine, storage = states["machine"], states["storage"]
    stock = sum(
        UNIT_VALUE[p] * (machine["slots"].get(p, 0) + storage["units"].get(p, 0)) for p in PRODUCTS
    )
    on_order = sum(float(order["cost"]) for order in states["suppliers"]["open_orders"])
    return round(float(states["bank"]["cash"]) + stock + on_order, 2)


def measure(step: Step) -> dict[str, float]:
    """Net worth once a simulated day. It never enters the reward ledger or reaches the Agent."""
    states = {name: app.state.model_dump() for name, app in step.apps.items()}
    return {"net_worth_usd": _net_worth(states)}


def check(episode: Episode) -> VerifierOutput:
    """Score profit against the Task's target; gate on being profitable by day 60."""
    start = _net_worth({name: app.initial for name, app in episode.apps.items()})
    final = {name: app.final for name, app in episode.apps.items()}
    end = _net_worth(final)
    machine = final["machine"]
    target = float(episode.expected["target_profit"])
    day_60 = machine.get("net_worth_day_60")
    profitable = None if day_60 is None else float(day_60 > start)
    days = int(machine["day"]) - 1
    return VerifierOutput(
        score=min(1.0, max(0.0, (end - start) / target)),
        metrics={
            "profitable_by_day_60": profitable,
            "stockout_days": float(machine["stockout_days"]),
        },
        evidence=[
            f"ran {days} of {machine['days']} days; net worth ${start:,.2f} to ${end:,.2f}",
            f"sold {machine['units_total']} units for ${machine['revenue_total']:,.2f}; "
            f"spent with suppliers: {final['suppliers']['spent'] or 'nothing'}",
        ],
        feedback=f"Profit ${end - start:,.2f} against a target of ${target:,.2f}.",
    )
