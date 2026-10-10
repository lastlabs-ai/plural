---
route: /docs/start/from-scratch
title: Start from scratch
order: 24
description: "Build a small Wordle game from an empty folder to a scored run: one App with an action, an Environment, two Tasks, a Verifier, and a Benchmark."
audience: all
nav: true
nav_group: Start
---
# Start from scratch

**You start with** an empty folder.

**You end with** a small Wordle game that any model can play, two puzzles, a Verifier
that grades them, and a Benchmark you can rerun. It takes about fifteen minutes, and
every block below can be pasted as it is.

## 1. Create a project

```bash
plural project init wordle
cd wordle
plural env init wordle
```

**What just happened.** `plural project init` made the project folder, and
`plural env init` wrote a template Environment in `environments/wordle/`. You will
replace its files in the next two steps.

## 2. Write one App with an action

An App is the moves an Agent can make. Replace `environments/wordle/environment.py`
with:

```python
"""A small Wordle: guess a hidden five-letter word in six tries."""

from plural import App, State, action, initial, rewarder


class Game(State):
    secret: str = initial("", description="The hidden five-letter word.")
    remaining: int = 6
    solved: bool = False


class Wordle(App[Game]):
    """Guess a hidden five-letter word in six tries."""

    def reset(self, initial_state):
        super().reset(initial_state)
        return "6 guesses left. Guess any five-letter word."

    @action
    def guess(self, word: str) -> str:
        """Guess one word. + is correct, ? is elsewhere in the word, - is absent."""
        word = word.strip().lower()
        if len(word) != 5 or not word.isalpha():
            raise ValueError("guess exactly five letters")
        marks = " ".join(
            "+" if letter == self.state.secret[i] else "?" if letter in self.state.secret else "-"
            for i, letter in enumerate(word)
        )
        self.state.remaining -= 1
        self.state.solved = word == self.state.secret
        status = "solved" if self.state.solved else f"{self.state.remaining} guesses left"
        return f"{word}  {marks}\n{status}"

    def terminated(self) -> bool:
        return self.state.solved or self.state.remaining <= 0

    @rewarder
    def solved(self, previous_state, current_state, action, result) -> float:
        """1 on the guess that solves the puzzle."""
        return float(current_state["solved"] and not previous_state["solved"])
```

**What just happened.**

- `Game` is the App's **State**, its private truth. The Agent never sees it.
  `initial()` marks `secret` as a field each Task sets.
- `guess` is an **action**. Its docstring is the description the model reads, and
  what it returns is all the model sees. Raising `ValueError` tells the model what
  went wrong, so it can try again.
- `terminated` ends the game.
- The `@rewarder` gives per-step credit for training. It never counts toward a score.

## 3. Describe the Environment

Replace `environments/wordle/environment.yaml` with:

```yaml
name: wordle
description: Guess a hidden five-letter word in six tries.
overview: Each guess is marked correct, present, or absent. The secret stays on State.
python: environment.py:Wordle
readme: README.md
runtime:
  provider: local
limits:
  max_turns: 6
  max_seconds: 120
```

Then write its README and check it:

```bash
echo "Guess a hidden five-letter word in six tries." > environments/wordle/README.md
plural env validate wordle
```

```text
environment/wordle is valid: sha256:2ade039e2f16...

App wordle (python, owned)
  guess
```

**What just happened.** The Environment is the App plus where it runs. The `local`
runtime runs the game directly on your machine, as a trusted subprocess, so you don't
need Docker. Use `provider: docker` to run each Trial in a container instead.

## 4. Write two Tasks

Each Task is one puzzle, with its own secret:

```bash
for word in crane slate; do
  plural task init $word --environment wordle --verifier solved
  echo "Guess the hidden five-letter word. Use the marks from each guess to choose the next." > tasks/$word/instruction.md
  printf 'name: %s\ninstructions: instruction.md\nenvironment: wordle\nverifiers:\n  - solved\ninitial_state:\n  secret: %s\n' $word $word > tasks/$word/task.yaml
done
cat tasks/crane/task.yaml
```

```yaml
name: crane
instructions: instruction.md
environment: wordle
verifiers:
  - solved
initial_state:
  secret: crane
```

**What just happened.** `initial_state` sets the App's `secret`. Because the secret is
State, the Agent sees only the instructions and what each guess returns.

## 5. Write a Verifier

```bash
plural verifier init solved
```

Replace `verifiers/solved/verify.py` with:

```python
"""Score 1 when the secret was guessed."""

from plural import Episode, VerifierOutput


def verify(episode: Episode) -> VerifierOutput:
    """Read the final State, which the Agent never saw."""
    solved = bool(episode.state.get("solved"))
    used = 6 - int(episode.state.get("remaining", 6))
    return VerifierOutput(score=float(solved), evidence=[f"solved={solved} after {used} guesses"])
```

**What just happened.** The Verifier grades what actually happened in the game, not the
model's claim that it won. Its `score` is what a Benchmark ranks on.

## 6. Group the Tasks into a Benchmark

```bash
plural benchmark init wordle
```

Replace `benchmarks/wordle/benchmark.yaml` with:

```yaml
name: wordle
description: Two Wordle puzzles.
purpose: Whether an Agent can use feedback to find a hidden word.
tasks: [crane, slate]
scoring:
  metric: Success rate
  description: Share of puzzles solved within six guesses.
```

```bash
echo "Two Wordle puzzles. A score is the share solved in six guesses." > benchmarks/wordle/README.md
plural benchmark validate wordle
```

## 7. Run a Job

```bash
plural run --benchmark wordle --model openai/gpt-5.6-luna
```

```text
Running benchmark/wordle local with gpt-5.6-luna (openai/gpt-5.6-luna) locally: 2 trial(s), 2 at a time (auto: every Trial at once).
  [1/2] trl_a3c4c32fe982f553d6eaf682  crane  succeeded  score=1.000  | 1 succeeded, 0 failed, mean 1.000
  [2/2] trl_7141ed163cc5f72c17a5c3a4  slate  succeeded  score=1.000  | 2 succeeded, 0 failed, mean 1.000
Job job_a9ecd47fc78ca7293e5bc68a succeeded.
  gpt-5.6-luna: mean score 1.000 over 2 trial(s), 2 succeeded
```

```bash
plural rewards show trl_7141ed163cc5f72c17a5c3a4
```

```text
step  e3     +0.000  app:solved
step  e5     +0.000  app:solved
step  e7     +1.000  app:solved
```

**What just happened.** The model played both puzzles through the `guess` action, the
Verifier scored each one, and the `solved` rewarder credited the winning guess. That
reward sits in the Trial's reward ledger for training. It didn't change the score.

## Where you are now

You have a Benchmark, `wordle`, that you can rerun on any model with
`plural run --benchmark wordle --model <model>`, or repeat exactly with
`plural job rerun <job-id>`. The other two paths end in the same place.

Next:

- The [Wordle tutorial](../tutorials/wordle.md) builds the full game, with Wordle's
  word list, an offline Agent, and the Python SDK.
- Connect a real system as a second App; see [Apps](../concepts/apps.md).
- Push the project and run it on Plural's servers; see
  [Getting started](../getting-started.md#push-and-run-hosted).
