"""The shop's reference policy: a cautious shopkeeper who stocks for an ordinary day.

`plural task validate` plays it on every Task through the normal engine, so a Task
whose reference loses money has a broken Task or a broken grader, not a weak
Agent. It reads only what an Agent reads: the books and each action's reply.
"""

import re

LINE = re.compile(
    r"^(?P<item>\w+): (?P<stock>\d+) on the shelf, priced \$(?P<price>[\d,.]+); "
    r"supplier charges \$(?P<cost>[\d,.]+)\.$",
    re.MULTILINE,
)
CASH = re.compile(r"Cash \$(-?[\d,]+\.\d{2})")
DAY = re.compile(r"Day (\d+) of (\d+)")
STOCK_FOR = {"coffee": 26, "bagel": 17, "juice": 9}
"""Units to have on the shelf each morning: a little under an ordinary day's demand."""
RESERVE = 30.0
"""Cash kept back for the rent, never spent on stock."""


def solve(task, environment):
    """Run the season: each day, read the books, top up the shelf, and open."""
    environment.reset()
    while True:
        books = _text(environment.step("books"))
        day, days = (int(value) for value in DAY.search(books).groups())
        cash = float(CASH.search(books).group(1).replace(",", ""))
        for match in LINE.finditer(books):
            item = match.group("item")
            cost = float(match.group("cost").replace(",", ""))
            wanted = STOCK_FOR.get(item, 0) - int(match.group("stock"))
            affordable = int(max(cash - RESERVE, 0) // cost)
            units = min(wanted, affordable)
            if units > 0:
                environment.step("buy", item=item, units=units)
                cash -= units * cost
        reply = _text(environment.step("wait"))
        if "season is over" in reply or day >= days:
            return f"Ran the shop for {days} days."


def _text(step):
    observation = step.observation
    if isinstance(observation, str):
        return observation
    if isinstance(observation, dict) and isinstance(observation.get("text"), str):
        return observation["text"]
    return str(observation)
