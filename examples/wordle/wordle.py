"""Wordle as a Plural Environment. The secret stays on State, never on Observation."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from plural import Environment, Observation, State, action, hidden

WORDS = ("crane", "slate", "audio", "point", "heart")
SECRETS = {"easy-01": "slate"}


class Board(Observation):
    remaining: int = 6
    solved: bool = False
    last_guess: str = ""
    last_marks: list[str] = Field(default_factory=list)


class Game(State):
    secret: str = hidden("")
    remaining: int = 6
    solved: bool = False
    guesses: list[str] = Field(default_factory=list)


def marks(secret: str, guess: str) -> list[str]:
    scored = ["absent"] * 5
    leftover = list(secret)
    for index, letter in enumerate(guess):
        if letter == secret[index]:
            scored[index] = "correct"
            leftover[index] = ""
    for index, letter in enumerate(guess):
        if scored[index] == "correct" or letter not in leftover:
            continue
        scored[index] = "present"
        leftover[leftover.index(letter)] = ""
    return scored


class Wordle(Environment[Board, Game]):
    name = "wordle"
    overview = "Guess a hidden five-letter word in six tries."
    reset_command = ("python", "commands.py", "reset")

    def __init__(self, *, secret: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        info = self.info if isinstance(self.info, dict) else {}
        self._secret = secret or SECRETS[str(info.get("task_id") or "easy-01")]

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[Board, dict[str, Any]]:
        del options
        super().reset(seed=seed)
        self.state = Game(secret=self._secret, remaining=6, seed=self.state.seed)
        self.observation = Board(text="empty board · 6 left", remaining=6)
        return self.observation, {}

    @action
    def guess(self, word: str) -> Board:
        word = word.strip().lower()
        if word not in WORDS:
            raise ValueError(f"{word!r} is not in the dictionary")
        scored = marks(self.state.secret, word)
        self.state.guesses.append(word)
        self.state.remaining -= 1
        self.state.solved = word == self.state.secret
        glyph = {"correct": "+", "present": "?", "absent": "-"}
        line = f"{word}  {' '.join(glyph[mark] for mark in scored)}"
        status = "solved" if self.state.solved else f"{self.state.remaining} left"
        self.observation = Board(
            text=f"{self.observation.text}\n{line}\n{status}".removeprefix(
                "empty board · 6 left\n"
            ),
            remaining=self.state.remaining,
            solved=self.state.solved,
            last_guess=word,
            last_marks=scored,
        )
        return self.observation

    def terminated(self) -> bool:
        return self.state.solved or self.state.remaining <= 0

    def reward(self, previous_state, current_state, action, result) -> float:
        del previous_state, current_state, action, result
        return 1.0 if self.state.solved else 0.0
