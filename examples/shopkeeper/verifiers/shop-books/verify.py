"""Read the shop's books: cash after every action, and the season's result."""

from plural import Episode, Step, VerifierOutput


def measure(step: Step) -> dict[str, float]:
    """Cash on hand after each action, charted over the season.

    It runs in the App host after every action, like a reward, but it is a
    measurement: it never enters the reward ledger or reaches the Agent.
    """
    books = step.current_state or {}
    return {"cash_on_hand": float(books["cash"])} if "cash" in books else {}


def check(episode: Episode) -> VerifierOutput:
    """Score the season by profit against the Task's target, and gate on never going negative.

    A shop that ever went below zero scores 0, however it ended. There is no
    final answer to read: the books in State are the whole result.
    """
    books = episode.state
    start = float(episode.expected["starting_cash"])
    target = float(episode.expected["target_profit"])
    cash = float(books["cash"])
    solvent = float(books["lowest_cash"]) >= 0
    profit = cash - start
    score = 0.0 if not solvent else min(1.0, max(0.0, profit / target))
    days_open = len(books.get("history") or [])
    series = episode.metric_series.get("cash_on_hand", ())
    low = min((value for _, value in series), default=cash)
    return VerifierOutput(
        score=score,
        metrics={"never_negative_cash": float(solvent)},
        evidence=[
            f"opened {days_open} of {books['days']} days; cash ${start:,.2f} to ${cash:,.2f} "
            f"(lowest ${min(low, float(books['lowest_cash'])):,.2f})"
        ],
        feedback=(
            "The shop went below zero cash."
            if not solvent
            else f"Profit ${profit:,.2f} against a target of ${target:,.2f}."
        ),
    )
