"""Score a negotiation: each seat's surplus, and its share of what a deal could make."""

from plural import Episode, Step, VerifierOutput

SEATS = ("seat_1", "seat_2")


def _surplus(state: dict, price: float | None) -> dict[str, float]:
    if price is None:
        return dict.fromkeys(SEATS, 0.0)
    return {"seat_1": round(state["value"] - price, 2), "seat_2": round(price - state["cost"], 2)}


def _on_table(state: dict) -> float | None:
    if state.get("ended") == "deal":
        return state["price"]
    if state.get("ended") or not state.get("offers"):
        return None
    return state["offers"][-1]["price"]


def measure(step: Step) -> dict[str, dict[str, float]]:
    """Each seat's surplus at the offer on the table, after every action."""
    state = step.apps["market"].state.model_dump()
    return {"surplus_usd": _surplus(state, _on_table(state))}


def check(episode: Episode) -> VerifierOutput:
    """Each seat scores its share of the possible surplus: value less cost."""
    state = episode.apps["market"].final
    price = state["price"] if state.get("ended") == "deal" else None
    surplus = _surplus(state, price)
    pie = state["value"] - state["cost"]
    shares = {seat: max(0.0, min(1.0, surplus[seat] / pie)) if pie > 0 else 0.0 for seat in SEATS}
    deal = price is not None
    return VerifierOutput(
        score=sum(shares.values()) / len(shares),
        seats=shares,
        metrics={"deal": float(deal)},
        evidence=[
            f"value ${state['value']:,.0f}, cost ${state['cost']:,.0f}; "
            + (f"deal at ${price:,.2f}" if deal else f"no deal ({state.get('ended')})")
            + f" after {len(state['offers'])} offers",
        ],
        feedback=f"Buyer surplus ${surplus['seat_1']:,.2f}, seller surplus ${surplus['seat_2']:,.2f}.",
    )
