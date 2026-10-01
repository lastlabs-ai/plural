---
route: /docs/tutorials/wordle
title: Wordle
order: 115
description: Walk through a Wordle project that keeps the secret word on State, score it with a deterministic Verifier, and run it from the CLI or the Python SDK.
audience: all
nav: true
nav_group: Tutorials
outcome: You can run and interpret a three-Task Wordle Benchmark from the CLI or Python, offline or with a model.
---
# Wordle

In this tutorial you run the word game Wordle as a Plural project. The game hides a
five-letter word. The AI guesses, sees which letters are right, and tries again until
it finds the word or runs out of guesses. A grader then marks each game as solved or
not.

Wordle is a good first project because you already know the rules, and because it
shows the most important idea in Plural clearly: **the game knows the secret, and the
AI never does.**

By the end you will have:

- seen how the project keeps the secret word hidden from the AI,
- run a three-game exam offline, from the command line and from Python,
- run it with a real model, and
- read the results, including every guess the AI made.

## Before you start

You need Plural installed; see [Install](../getting-started.md#install). The project is
`examples/wordle` in the [Plural repository](https://github.com/lastlabs-ai/plural).
Copy it anywhere and run the commands from inside it:

```bash
git clone https://github.com/lastlabs-ai/plural.git
cp -R plural/examples/wordle wordle
cd wordle
```

No account or key is needed until [Run it with a model](#run-it-with-a-model).

## What is in the project

In the words from [Core concepts](../getting-started/concepts.md), this tutorial uses:

- **The world** (Environment): `wordle`, the game itself.
- **Three assignments** (Tasks): `crane`, `slate`, and `point`, each with one secret word.
- **The grader** (Verifier): `solved`, which checks whether the word was found.
- **The exam** (Benchmark): `wordle`, the three games together.
- **Two contestants** (Agents): `word-list`, which guesses from a fixed list and calls no
  model, and `luna`, a real model.

On disk:

```text
environments/wordle/            environment.yaml, environment.py, README.md, words.txt
tasks/crane/, slate/, point/    task.yaml, instruction.md (one secret word each)
verifiers/solved/               verifier.yaml, verify.py
harnesses/word-list/            harness.yaml, harness.py (guesses a fixed list, no model)
agents/word-list/               agent.yaml (runs the word-list Harness)
agents/luna/                    agent.yaml (a model on the native harness)
benchmarks/wordle/              benchmark.yaml, README.md
run.py                          the same run from the Python SDK
```

`project.yaml`, `plural.lock`, and `pyproject.toml` sit at the top, as in every
project.

The folder also holds a larger exam you can try once you have finished:
`benchmarks/wordlebench` (seven more games, `case-01` to `case-03`, `medium-01`,
`medium-02`, `hard-01`, and `hard-02`), two more model Agents (`plain` and `tracker`),
and a `board` Harness. [Extend it](#extend-it) shows how to use them.

### The Environment keeps the secret on State

The Environment is the game. `environments/wordle/environment.py` separates what the
game knows from what the AI sees:

- **State** is the full truth: the secret word and the list of guesses so far.
- The **Observation** is only the board: its text (the last guess and its marks), the
  guesses remaining, and whether the puzzle is solved.

```python
class Board(Observation):
    remaining: int = 6
    solved: bool = False


class Game(State):
    secret: str = initial(
        "",
        description="The hidden five-letter word. Empty picks one from words.txt using the seed.",
        max_length=5,
        pattern=r"^([a-z]{5})?$",
    )
    remaining: int = 6
    solved: bool = False
    guesses: list[str] = Field(default_factory=list)
```

`initial()` marks `secret` as a field a Task may set. That is how each Task chooses its
word.

The game has one move, `guess`. It checks the word against the list of accepted words,
marks each letter, and updates the board. The accepted words live in `words.txt` next
to the Environment, one per line: the 14,855 guesses Wordle accepts. `words()` reads
the file once:

```python
WORDS_FILE = Path(__file__).with_name("words.txt")


class Wordle(Environment[Board, Game]):
    @staticmethod
    @cache
    def words() -> frozenset[str]:
        """Every word the game accepts, one per line in words.txt. Read once per process."""
        lines = WORDS_FILE.read_text(encoding="utf-8").splitlines()
        return frozenset(line.strip().lower() for line in lines if line.strip())

    @action
    def guess(
        self,
        word: Annotated[str, Field(min_length=5, max_length=5, pattern=r"^[a-z]{5}$")],
    ) -> Board:
        """Guess one word. + is correct, ? is elsewhere in the word, - is absent."""
        word = word.strip().lower()
        if word not in self.words():
            raise ValueError(f"{word!r} is not in the word list")
        ...
```

`word` has to be exactly five lowercase letters. That limit is part of the action
schema, so the model and the Actions tab both see it.

The marks are Wordle's colors written as symbols: `+` is the right letter in the right
place (green), `?` is in the word somewhere else (yellow), and `-` is not in the word
(gray). The docstring on `guess` is the description the AI reads. The game ends when
`terminated()` sees the puzzle solved or no guesses left.

Files beside `environment.py` travel with the Environment, so the word list is there in
a container or a hosted run too.

`environment.yaml` names the class, the runtime, and the limits on each attempt:

```yaml
name: wordle
version: 0.1.0
description: Guess a hidden five-letter word. Each guess is marked correct, present, or absent.
overview: Six guesses. The secret stays on State, and the Agent only sees the board.
python: environment.py:Wordle
readme: README.md
resources: []
runtime:
  provider: local
harness_policy:
  mode: allow_all
limits:
  max_turns: 6
  max_seconds: 120
```

The `local` runtime runs the game directly on your machine, as a trusted subprocess.
It is not a sandbox. `provider: docker` runs each Trial in a container instead, and
`plural run` adds Plural to its image for you.

### Each Task sets one secret

A Task is one game. `tasks/crane/task.yaml`:

```yaml
name: crane
version: 0.1.0
instructions: instruction.md
environment: wordle
verifiers:
  - solved
initial_state:
  secret: crane
```

`slate` and `point` differ only in their name and secret. Because the secret is State,
the AI never sees it. It sees `instruction.md` and the board, nothing else.

### The Verifier reads the final State

The Verifier is the grader. `verifiers/solved/verifier.yaml` declares a deterministic
Verifier (a `DeterministicVerifier` in Python), meaning a small piece of code that
checks the answer exactly. It points at the `verify` function in `verify.py`:

```yaml
name: solved
version: 0.1.0
kind: deterministic
check: verify.py:verify
weight: 1
```

The check reads the final State, which the AI never saw:

```python
from plural import Episode, VerifierOutput


def verify(episode: Episode) -> VerifierOutput:
    """Score 1 when the secret was guessed and 0 otherwise. Report guesses used."""
    guesses = episode.state.get("guesses") or []
    solved = bool(episode.state.get("solved"))
    detail = f"solved in {len(guesses)}" if solved else f"unsolved after {len(guesses)}"
    return VerifierOutput(
        score=float(solved),
        scores={"guesses": float(len(guesses))},
        evidence=[detail],
    )
```

The grader looks at what actually happened in the game, not at the AI's claim that it
won. `score` is what the Benchmark ranks on. The `guesses` sub-score shows how
efficiently each puzzle was solved, but it does not affect ranking.

### Two Agents

The Agents are the contestants.

`agents/word-list/agent.yaml` runs the `word-list` Harness, which guesses the words
listed in `harnesses/word-list/harness.yaml` in order and calls no model. The `model`
is recorded but never called, and with `auth_mode: none` the Agent needs no
credential:

```yaml
name: word-list
version: 0.1.0
model: openai/gpt-5.6-luna
harness: word-list
auth_mode: none
```

`agents/luna/agent.yaml` is a model with instructions. It names no Harness, so it uses
`native`, Plural's built-in tool loop:

```yaml
name: luna
version: 0.1.0
model: openai/gpt-5.6-luna
instructions: Play Wordle with the guess action. Use the marks to narrow the word, and stop as soon as it is solved.
```

That is everything. Time to play.

## Run it offline

Start with the `word-list` Agent. It needs no account or key, so it is the quickest
way to check the project is wired correctly. Validate the Benchmark, which also checks
every Task, Verifier, and Environment it uses, then run it:

```bash
plural benchmark validate wordle
plural run --benchmark wordle --agent word-list
```

You should see the Benchmark confirmed as valid, then one line per game as it
finishes. Your ids will differ, and the games may finish in a different order:

```text
benchmark/wordle is valid: version 1.0.0, sha256:c8e29b50c50ecd2863a61e7ce2b8daa96f083cc00d0fb56f88c58cbba75e5d99
Running benchmark/wordle@1.0.0 with word-list (openai/gpt-5.6-luna) locally: 3 trial(s), 3 at a time (auto: every Trial at once).
  [1/3] trl_c53f6596c1834b751964f862  crane  succeeded  score=1.000  | 1 succeeded, 0 failed, mean 1.000
  [2/3] trl_ccd3f1712d34eddbd923e951  slate  succeeded  score=1.000  | 2 succeeded, 0 failed, mean 1.000
  [3/3] trl_3aba06619e94795c19a42df5  point  succeeded  score=1.000  | 3 succeeded, 0 failed, mean 1.000
Job job_68c5dde6a6c6f1aa9303254f succeeded.
  word-list: mean score 1.000 over 3 trial(s), 3 succeeded
Details: plural job show job_68c5dde6a6c6f1aa9303254f
```

Three for three. The whole run is one **Job**, and each game is a **Trial**: three
Tasks and one Agent make three Trials.

Don't read too much into the perfect score. The `word-list` Harness guesses crane,
slate, audio, point, and heart in that order, which covers these three secrets, so it
always wins. It proves the project works, not that anything plays well.

## Run it from Python

Everything the command line does, you can also do from Python. `run.py` loads the same
pieces by name and runs the same Benchmark with the same Agent:

```python
from pathlib import Path

from plural import Job
from plural.project import Project, Workspace

if __name__ == "__main__":
    workspace = Workspace(Project.find(Path(__file__).parent))
    benchmark = workspace.get("benchmark", "wordle")
    agent = workspace.get("agent", "word-list")
    result = Job(benchmark, agents=[agent]).run()
    for trial in result.trials:
        print(f"{trial.receipt.task_pin.name}: score={trial.score}")
```

`Project.find()` looks upward from the directory you give it, or from the current
directory, to find `project.yaml`. Run the script with the Python environment you
installed Plural into:

```bash
python run.py
```

You should see one score per game:

```text
crane: score=1.0
slate: score=1.0
point: score=1.0
```

> **Good to know:** The Python run executes locally like `plural run`, but it is not
> recorded as a Job. It does not appear in `plural job list`, and `plural job rerun`
> cannot repeat it.

## Run it with a model

Now let a real model play. This calls a model through the Plural gateway and can
incur charges.

Every model call needs a Plural API key. `plural auth login` stores one for you, or
create one in the web app under Keys and store it with
`plural auth login --api-key-stdin` or export `PLURAL_API_KEY`. Then try one game, and
the whole Benchmark:

```bash
plural run --task crane --model openai/gpt-5.6-luna
plural run --benchmark wordle --agent luna
```

`--model` without `--harness` uses `native`, the same loop the `luna` Agent uses. The
model sees `instruction.md` and the board after each guess. It never sees the secret,
the score, or any reward.

## Read the results

Three commands take you from the overview down to one game:

```bash
plural job list
plural job show <job-id>
plural trial show <trial-id>
```

`job show` lists each word with its status and score. `trial show` prints the grader's
evidence and where the game's files are kept:

```text
Trial trl_3aba06619e94795c19a42df5 (local) succeeded
  Job:            job_68c5dde6a6c6f1aa9303254f
  Task:           point
  Score:          1.0
  Artifacts:      /path/to/wordle/.plural/jobs/job_68c5dde6a6c6f1aa9303254f/trials/trl_3aba06619e94795c19a42df5/executions/0/artifacts
  Logs:           /path/to/wordle/.plural/jobs/job_68c5dde6a6c6f1aa9303254f/trials/trl_3aba06619e94795c19a42df5/executions/0/logs
  Verifier solved: succeeded score=1.0
    - solved in 4
```

`point` was the fourth word on the list, so it was solved in 4.

> **Good to know:** A Trial that succeeded can still score 0. That is a missed word,
> not a crashed run.

If two words score differently, look at the guesses before you change the model or the
instructions. `plural job rerun <job-id>` repeats a Job with exactly the inputs it
pinned.

### What is in the Artifacts folder

The `Artifacts` directory holds the full record of the game:

- `episode.jsonl`: each guess, with the board the AI saw after it and the
  Environment's display view.
- `trajectory.json`: the same guesses as the AI's chat messages, turn by turn.
- `atif-trajectory.json`: the same turns in ATIF, with each call's tokens and cost.
- `state.json`: the secret and the guess history.
- `observation.json`: the final board the AI saw.
- `view.json`: the final display view, the grid of guesses and marks that the run
  viewer draws.

The score and the `guesses` sub-score are in the Trial's `result.json`. The display
view shows guesses and marks, never the secret; see
[Display views](../project/environments.md#display-views).

## Extend it

Once the basics work, the project has room to grow.

**Compare how Agents play.** `plain` is a model on the native loop. `tracker` is the
same model on the `board` Harness, which keeps a running record of every mark and
shows the model that record each turn, never the secret. Run both on the larger
seven-game exam and compare them (these call a model):

```bash
plural run --benchmark wordlebench --agent plain
plural run --benchmark wordlebench --agent tracker
```

A few more directions:

- **Judge how the Agent played, not only whether it won,** with an
  [AgentVerifier](../project/verifiers.md#agentverifier) or a
  [HumanVerifier](../project/verifiers.md#humanverifier).
- **Give per-guess credit for training.** The game already defines a `reward()` that
  gives 1 point for the guess that solves the word. You can change it or add a
  `@rewarder`; see [Rewards](../project/environments.md#rewards). Rewards are recorded
  on the episode and never contribute to the score.

## Push it and run hosted

To have Plural run the games for you, push the project to a private hosted project.
This needs a Plural account:

```bash
plural auth login
plural project init wordle --push
plural benchmark push wordle --with-deps
plural agent push luna --with-deps
plural run --benchmark wordle --agent luna --hosted --follow
```

`project init --push` registers the project, named `wordle` in `project.yaml`, with a
new private hosted project and selects it as your scope. If `wordle` already exists in
the account, add `--connect` to use it. `--with-deps` also pushes the Tasks, Verifier,
and Environment the Benchmark uses. `--hosted` runs the pushed revisions, first pushing
any input the hosted project does not hold yet, and `--follow` streams progress until
the Job finishes.

> **Good to know:** Pushing never makes anything public. Sharing is a separate action
> in the Plural web app.

## Where to go next

- Build your own project with [Getting started](../getting-started.md#add-resources).
- Read [Environments](../project/environments.md) to design a world of your own.
- Try the [support queue tutorial](support-queue.md) for a project with several moves
  per Task.
