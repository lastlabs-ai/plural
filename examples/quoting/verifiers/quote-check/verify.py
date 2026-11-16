"""Check one answered RFQ against the mill's State and the Task's answer key."""

from plural import Episode, VerifierOutput

# Benchmark canary: an Agent that writes this read a grader file.
CANARY = "plural-canary-8249360b-8ab7-4356-9960-eba8ebecfe72"

GATES = ("decision_correct", "price_correct", "delivery_feasible", "above_cost")


def check(episode: Episode) -> VerifierOutput:
    """Score 1 when the Agent made the right call and every check on its quote passes.

    The answer key says whether the request should be quoted or handed off, and for a
    quote, the grade and short tons. The price, the earliest delivery, and the cost come
    from State, because the price moves on each lookup.
    """
    state = episode.state
    expected = episode.expected
    quote = state.get("quote")
    decided = "quote" if quote else "handoff" if state.get("handoff") else "nothing"
    scores = {"decision_correct": float(decided == expected["decision"])}
    problems = []
    if decided != expected["decision"]:
        problems.append(f"expected a {expected['decision']}, but the Agent sent {decided}")
    if quote:
        scores.update(_quote_scores(quote, state, expected, problems))
    passed = all(scores[name] == 1.0 for name in GATES if name in scores)
    return VerifierOutput(
        score=float(passed),
        scores=scores,
        evidence=[_summary(quote, state)],
        feedback="; ".join(problems) or "Every check passed.",
    )


def _quote_scores(quote, state, expected, problems):
    grade, tons = quote["grade"], quote["tons"]
    given = state["prices_given"].get(grade)
    right_order = grade == expected.get("grade", grade) and tons == expected.get("tons", tons)
    if not right_order:
        problems.append(
            f"quoted {tons:g} t of {grade}, but the request was for "
            f"{expected.get('tons', tons):g} t of {expected.get('grade', grade)}"
        )
    if given is None:
        problems.append(f"quoted {grade} without looking up today's price")
        right_price = False
    else:
        right_price = (
            abs(quote["price_per_ton"] - given) < 0.005
            and abs(quote["total_price"] - round(given * tons, 2)) <= 0.01
        )
        if not right_price:
            problems.append(
                f"quoted ${quote['price_per_ton']:,.2f}/t for ${quote['total_price']:,.2f}; "
                f"today's price was ${given:,.2f}/t for ${given * tons:,.2f}"
            )
    feasible = quote["delivery_date"] >= quote["earliest_delivery"]
    if not feasible:
        problems.append(
            f"promised {quote['delivery_date']}, but the earliest the mill could deliver "
            f"was {quote['earliest_delivery']}"
        )
    cost = state["costs"][grade]
    above_cost = quote["price_per_ton"] >= cost
    if not above_cost:
        problems.append(f"quoted below the mill's cost of ${cost:,.2f}/t")
    return {
        "price_correct": float(right_order and right_price),
        "delivery_feasible": float(feasible),
        "above_cost": float(above_cost),
        "margin_usd": round((quote["price_per_ton"] - cost) * tons, 2),
    }


def _summary(quote, state):
    if quote:
        return (
            f"quoted {quote['tons']:g} t of {quote['grade']} at ${quote['price_per_ton']:,.2f}/t, "
            f"delivery {quote['delivery_date']}"
        )
    if state.get("handoff"):
        return f"handed off: {state['handoff']}"
    return "answered without a quote or a handoff"
