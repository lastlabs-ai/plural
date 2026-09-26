"""Wordle as a Plural Environment. The secret stays on State, never on Observation."""

import random
from functools import cache
from pathlib import Path

from pydantic import Field

from plural import Environment, Observation, State, action, initial

WORDS_FILE = Path(__file__).with_name("words.txt")


class Board(Observation):
    """The board the Agent sees. It never includes the secret."""

    remaining: int = 6
    solved: bool = False


class Game(State):
    """Private world. A Task may set the secret; the Environment owns the rest."""

    secret: str = initial(
        "",
        description="The hidden five-letter word. Empty picks one from words.txt using the seed.",
        max_length=5,
        pattern=r"^([a-z]{5})?$",
    )
    remaining: int = 6
    solved: bool = False
    guesses: list[str] = Field(default_factory=list)


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


class Wordle(Environment[Board, Game]):
    name = "wordle"
    overview = "Guess a hidden five-letter word in six tries."

    @staticmethod
    @cache
    def words() -> frozenset[str]:
        """Every word the game accepts, one per line in words.txt. Read once per process."""
        lines = WORDS_FILE.read_text(encoding="utf-8").splitlines()
        return frozenset(line.strip().lower() for line in lines if line.strip())

    def reset(self, *, seed=None, options=None):
        """Start an episode. A blank secret is chosen from words.txt using the seed."""
        super().reset(seed=seed, options=options)
        words = self.words()
        secret = self.state.secret or random.Random(self.state.seed).choice(sorted(words))
        if secret not in words:
            raise ValueError(f"The secret {secret!r} is not in words.txt")
        self.state = Game(secret=secret, remaining=6, seed=self.state.seed)
        self.observation = Board(text="6 guesses left. Guess any five-letter word.", remaining=6)
        return self.observation, {}

    @action
    def guess(self, word: str) -> Board:
        """Guess one word. + is correct, ? is elsewhere in the word, - is absent."""
        word = word.strip().lower()
        if word not in self.words():
            raise ValueError(f"{word!r} is not in the word list")
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

    def reward(self, previous_state, current_state, action, result) -> float:
        """One point for the guess that solves the word. Never part of the score."""
        return 1.0 if current_state["solved"] and not previous_state["solved"] else 0.0

    def view(self):
        """The board as the run viewer draws it: guesses and their marks, not the secret."""
        rows = [
            {"letters": guess, "marks": marks(self.state.secret, guess)}
            for guess in self.state.guesses
        ]
        if self.state.solved:
            status = f"Solved in {len(rows)}"
        elif self.state.remaining <= 0:
            status = "Out of guesses"
        else:
            status = f"{self.state.remaining} guesses left"
        return {
            "schema": "plural.view/v1",
            "kind": "marks-grid",
            "title": "Wordle",
            "columns": 5,
            "max_rows": 6,
            "rows": rows,
            "status": status,
        }
