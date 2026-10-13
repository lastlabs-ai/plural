"""Wordle as a Plural App. The secret stays on State; the Agent only sees what guess returns."""

import random
from functools import cache
from pathlib import Path
from typing import Annotated

from pydantic import Field

from plural import App, State, action, initial

WORDS_FILE = Path(__file__).with_name("words.txt")
GUESSES = 6
GLYPHS = {"correct": "+", "present": "?", "absent": "-"}


class Game(State):
    """The game's private truth. A Task sets the secret; the App owns the rest."""

    secret: str = initial(
        "",
        description="The hidden five-letter word. Empty picks one from words.txt using the seed.",
        max_length=5,
        pattern=r"^([a-z]{5})?$",
    )
    guesses: list[str] = Field(default_factory=list)
    found: str = "....."
    solved: bool = False


def marks(secret: str, guess: str) -> list[str]:
    """Score one guess: correct, present (right letter, wrong place), or absent."""
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


class Wordle(App[Game]):
    """Guess a hidden five-letter word in six tries."""

    @staticmethod
    @cache
    def words() -> frozenset[str]:
        """Every word the game accepts, one per line in words.txt. Read once per process."""
        lines = WORDS_FILE.read_text(encoding="utf-8").splitlines()
        return frozenset(line.strip() for line in lines if line.strip())

    def reset(self, initial_state):
        """Start a game. A blank secret is chosen from words.txt using the seed."""
        super().reset(initial_state)
        secret = self.state.secret or random.Random(self.state.seed).choice(sorted(self.words()))
        if secret not in self.words():
            raise ValueError(f"The secret {secret!r} is not in words.txt")
        self.state = Game(secret=secret, seed=self.state.seed)
        return f"{GUESSES} guesses left. Guess any five-letter word."

    @action
    def guess(
        self,
        word: Annotated[str, Field(min_length=5, max_length=5, pattern=r"^[a-z]{5}$")],
    ) -> str:
        """Guess one word. + is correct, ? is elsewhere in the word, - is absent."""
        if word not in self.words():
            raise ValueError(f"{word!r} is not in the word list")
        scored = marks(self.state.secret, word)
        self.state.guesses.append(word)
        self.state.found = "".join(
            letter if mark == "correct" else known
            for letter, mark, known in zip(word, scored, self.state.found, strict=True)
        )
        self.state.solved = word == self.state.secret
        left = GUESSES - len(self.state.guesses)
        status = "solved" if self.state.solved else f"{left} left"
        return f"{word}  {' '.join(GLYPHS[mark] for mark in scored)}\n{status}"

    def terminated(self) -> bool:
        return self.state.solved or len(self.state.guesses) >= GUESSES

    def view(self):
        """The board as the run viewer draws it: guesses and their marks, never the secret."""
        rows = [
            {"letters": guess, "marks": marks(self.state.secret, guess)}
            for guess in self.state.guesses
        ]
        if self.state.solved:
            status = f"Solved in {len(rows)}"
        elif len(rows) >= GUESSES:
            status = "Out of guesses"
        else:
            status = f"{GUESSES - len(rows)} guesses left"
        return {
            "schema": "plural.view/v1",
            "kind": "marks-grid",
            "title": "Wordle",
            "columns": 5,
            "max_rows": GUESSES,
            "rows": rows,
            "status": status,
        }
