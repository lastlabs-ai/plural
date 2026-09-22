"""Wordle as a Plural Environment. The secret stays on State, never on Observation."""

import random

from pydantic import Field

from plural import Environment, Observation, State, action, initial

WORDS = ("crane", "slate", "audio", "point", "heart")


class Board(Observation):
    remaining: int = 6
    solved: bool = False


class Game(State):
    secret: str = initial(
        "",
        description="The hidden word for this Task.",
        min_length=5,
        max_length=5,
        pattern=r"^[a-z]{5}$",
    )
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

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        secret = random.Random(self.state.seed).choice(WORDS)
        self.state = Game(secret=secret, remaining=6, seed=self.state.seed)
        self.observation = Board(text="6 guesses left", remaining=6)
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
        glyphs = {"correct": "+", "present": "?", "absent": "-"}
        marks_text = " ".join(glyphs[mark] for mark in scored)
        status = "solved" if self.state.solved else f"{self.state.remaining} left"
        self.observation = Board(
            text=f"{word}  {marks_text}\n{status}",
            remaining=self.state.remaining,
            solved=self.state.solved,
        )
        return self.observation

    def terminated(self) -> bool:
        return self.state.solved or self.state.remaining <= 0
