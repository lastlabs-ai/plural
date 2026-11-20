"""A Harness that haggles by a fixed concession schedule instead of calling a model."""

import re

from plural import Harness, HarnessResult

MONEY = r"\$([\d,]+(?:\.\d+)?)"


def _money(text):
    return float(text.replace(",", ""))


class SteadyHaggler(Harness):
    auth = ("none",)

    def run(self, task, agent, environment):
        """Wait for this seat's turn, read its view, and make one move, until the talks end."""
        moves = 0
        while True:
            view = environment.wait_for_turn()
            if view.done:
                return HarnessResult(response=f"Made {moves} moves.")
            text = view.observation.get("text", "") if isinstance(view.observation, dict) else ""
            name, arguments = self._move(text, moves)
            environment.step(name, **arguments)
            moves += 1

    def _move(self, text, moves):
        buyer = "You are the buyer" in text
        limit = _money(re.search(MONEY, text).group(1))
        theirs = [_money(price) for price in re.findall(r"They offered " + MONEY, text)]
        left = re.search(r"(\d+) offers left", text)
        left = int(left.group(1)) if left else 0
        margin = float(self.config.get("open_margin", 0.6))
        concede = float(self.config.get("concede", 0.2))
        anchor = limit * (1 - margin) if buyer else limit * (1 + margin)
        mine = round(anchor + (limit - anchor) * (1 - (1 - concede) ** moves), 0)
        if theirs:
            offer = theirs[-1]
            acceptable = offer <= limit if buyer else offer >= limit
            as_good = offer <= mine if buyer else offer >= mine
            if acceptable and (as_good or left <= 1):
                return "accept", {}
        return "offer", {"price": mine}
