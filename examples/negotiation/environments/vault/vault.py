"""A vault two partners open together: each holds half of the code.

``seat_1`` knows the first two digits and ``seat_2`` the last two. They take
turns, and share one board to talk on. Either may try the full code; three
wrong tries lock the vault for good.
"""

from typing import Any

from pydantic import Field

from plural import App, State, action, initial


class VaultState(State):
    """The code, the board, and the tries so far."""

    max_moves: int = initial(12, description="Moves allowed between the two partners.")
    code: str = ""
    board: list[str] = Field(default_factory=list)
    tries: int = 0
    moves: int = 0
    opened: bool = False


class Vault(App[VaultState]):
    """Post on the shared board, or try the code."""

    name = "vault"

    def reset(self, state: Any) -> Any:
        observation = super().reset(state)
        self.state.code = "".join(str(self.rng.randrange(10)) for _ in range(4))
        return observation

    def _move(self) -> None:
        if self.terminated():
            raise ValueError("The vault is closed to you now.")
        self.state.moves += 1

    @action
    def post(self, message: str) -> str:
        """Write a message on the board your partner reads. Then it's their move."""
        self._move()
        self.state.board = [*self.state.board, f"{self.seat}: {message[:300]}"]
        return "Posted."

    @action
    def open_vault(self, code: str) -> str:
        """Try the full four-digit code. Three wrong tries lock the vault."""
        self._move()
        self.state.tries += 1
        if code.strip() == self.state.code:
            self.state.opened = True
            return "The vault opens."
        return f"Wrong code. {3 - self.state.tries} tries left."

    def turn(self) -> str:
        return self.seats[self.state.moves % len(self.seats)]

    def observe(self, seat: str) -> dict[str, Any]:
        half = self.state.code[:2] if seat == "seat_1" else self.state.code[2:]
        which = "first" if seat == "seat_1" else "last"
        lines = [
            f"You hold the {which} two digits of the code: {half}.",
            f"Tries left: {3 - self.state.tries}. Moves left: "
            f"{self.state.max_moves - self.state.moves}.",
            "Board:",
            *(self.state.board or ["(empty)"]),
        ]
        if self.state.opened:
            lines.append("The vault is open.")
        return {"text": "\n".join(lines)}

    def terminated(self) -> bool:
        return (
            self.state.opened or self.state.tries >= 3 or self.state.moves >= self.state.max_moves
        )
