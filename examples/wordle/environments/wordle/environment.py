"""Wordle as a Plural Environment. The secret stays on State, never on Observation."""

import random

from pydantic import Field

from plural import Environment, Observation, State, action, initial

# Legal guesses. The Environment chooses which of these, if any, to print.
EASY = ("crane", "slate", "audio", "point", "heart")
MEDIUM = ("storm", "grape", "flame", "brick", "smile", "cabin", "river", "crane", "slate", "audio")
WORDS = EASY + ("storm", "grape", "flame", "brick", "smile", "cabin", "river", "crypt", "nymph", "fjord", "glyph", "axiom", "bayou")


class Board(Observation):
    """The board the Agent sees. It never includes the secret."""

    remaining: int = 6
    solved: bool = False


class Game(State):
    """Private world. A Task may set the secret; the Environment owns the rest."""

    secret: str = initial(
        "",
        description="The hidden five-letter word. Empty picks one from the word list using the seed.",
        max_length=5,
        pattern=r"^([a-z]{5})?$",
    )
    remaining: int = 6
    solved: bool = False
    guesses: list[str] = Field(default_factory=list)


def _shown(secret: str) -> tuple[str, ...] | None:
    """The list the board prints. None means the Environment keeps the dictionary private."""
    if secret in EASY:
        return EASY
    if secret in MEDIUM:
        return MEDIUM
    return None


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

    def reset(self, *, seed=None, options=None):
        """Start an episode. A blank secret is chosen from the word list."""
        super().reset(seed=seed, options=options)
        secret = self.state.secret or random.Random(self.state.seed).choice(WORDS)
        self.state = Game(secret=secret, remaining=6, seed=self.state.seed)
        shown = _shown(secret)
        if shown:
            listed = f" Words: {', '.join(shown)}."
        else:
            listed = " Guess any five-letter dictionary word."
        self.observation = Board(text=f"6 guesses left.{listed}", remaining=6)
        return self.observation, {}

    @action
    def guess(self, word: str) -> Board:
        """Guess one word. + is correct, ? is elsewhere in the word, - is absent."""
        word = word.strip().lower()
        allowed = _shown(self.state.secret) or WORDS
        if word not in allowed:
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
