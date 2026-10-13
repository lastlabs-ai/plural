"""A channel every seat reads, a private note for each seat, and turns."""

from typing import Any

from plural import App, State, action


class Board(State):
    messages: list[dict[str, Any]] = []
    notes: dict[str, str] = {}
    posts: int = 0


class Thread(App[Board]):
    def reset(self, initial_state: Any) -> None:
        super().reset(initial_state)
        self.state.notes = {seat: f"secret-for-{seat}" for seat in self.seats}

    @action
    def post(self, text: str) -> str:
        self.state.messages.append({"seat": self.seat, "text": text})
        self.state.posts += 1
        return "posted"

    def turn(self) -> str:
        return self.seats[self.state.posts % len(self.seats)]

    def observe(self, seat: str) -> dict[str, Any]:
        return {"thread": self.state.messages, "note": self.state.notes.get(seat)}

    def terminated(self) -> bool:
        return self.state.posts >= 2 * len(self.seats)
