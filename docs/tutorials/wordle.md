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

The Environment hides a five-letter word. The Agent calls `guess`, gets letter marks,
and tries again until it solves the word or runs out of guesses. A deterministic
Verifier scores 1 when the puzzle is solved.

The project is `examples/wordle` in the [Plural repository](https://github.com/lastlabs-ai/plural).
You need Plural installed; see [Install](../getting-started.md#install). Copy the
project anywhere and run the commands from inside it:

```bash
git clone https://github.com/lastlabs-ai/plural.git
cp -R plural/examples/wordle wordle
cd wordle
```

No account or key is needed until [Run it with a model](#run-it-with-a-model).

## What is in the project

```text
environments/wordle/            environment.yaml, environment.py, README.md
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

### The Environment keeps the secret on State

`environments/wordle/environment.py` separates what the game knows from what the
Agent sees. The secret and the guess history are State. The Observation is only the
board: its text (the allowed words at the start, then the last guess and its marks),
the guesses remaining, and whether the puzzle is solved:

```python
class Board(Observation):
    remaining: int = 6
    solved: bool = False


class Game(State):
    secret: str = initial(
        "",
        description="The hidden word for this Task. Empty picks one from the seed.",
        max_length=5,
        pattern=r"^([a-z]{5})?$",
    )
    remaining: int = 6
    solved: bool = False
    guesses: list[str] = Field(default_factory=list)
```

`initial()` marks `secret` as a field a Task may set. The dictionary is five words:
crane, slate, audio, point, and heart. The one action checks the guess against the
dictionary, marks each letter, and updates the board:

```python
@action
def guess(self, word: str) -> Board:
    """Guess one word; + is right, ? is elsewhere in the word, - is absent."""
    word = word.strip().lower()
    if word not in WORDS:
        raise ValueError(f"{word!r} is not in the dictionary")
    ...
```

`+` is the right letter in the right place, `?` is in the word elsewhere, and `-` is
absent. The docstring is the description the Agent reads. The episode ends when
`terminated()` sees the puzzle solved or no guesses left.

`environment.yaml` names the class and the runtime. The `local` runtime is a trusted
subprocess on your machine, not a sandbox:

```yaml
name: wordle
version: 1.0.0
description: Guess a hidden five-letter word in six tries.
overview: Guess a hidden five-letter word in six tries.
python: environment.py:Wordle
readme: README.md
runtime:
  provider: local
harness_policy:
  mode: allow_all
limits:
  max_turns: 8
  max_seconds: 60
```

### Each Task sets one secret

`tasks/crane/task.yaml`:

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
the Agent never sees it; it sees `instruction.md` and the board.

### The Verifier reads the final State

`verifiers/solved/verifier.yaml` declares a deterministic Verifier (a
`DeterministicVerifier` in Python) and points at the `verify` function in `verify.py`:

```yaml
name: solved
version: 0.1.0
kind: deterministic
check: verify.py:verify
weight: 1
```

The check reads the final State, which the Agent never saw:

```python
from plural import Episode, VerifierOutput


def verify(episode: Episode) -> VerifierOutput:
    """Score 1 when the puzzle is solved and 0 otherwise; report the guesses used."""
    guesses = episode.state.get("guesses") or []
    solved = bool(episode.state.get("solved"))
    detail = f"solved in {len(guesses)}" if solved else f"unsolved after {len(guesses)}"
    return VerifierOutput(
        score=float(solved),
        scores={"guesses": float(len(guesses))},
        evidence=[detail],
    )
```

The Verifier reads the completed episode, not the Agent's claim that it finished.
`score` is what the Benchmark ranks on. The `guesses` sub-score shows how efficiently
each puzzle was solved, but it does not affect ranking.

### Two Agents

`agents/word-list/agent.yaml` runs the `word-list` Harness, which guesses the words
configured in `harnesses/word-list/harness.yaml` in order and calls no model. The
`model` is recorded but never called, and with `auth_mode: none` the Agent needs no
credential:

```yaml
name: word-list
version: 0.1.0
model: openai/gpt-5.6-luna
harness: word-list
auth_mode: none
```

`agents/luna/agent.yaml` is a model with instructions. It names no harness, so it uses
`native`, Plural's built-in tool loop:

```yaml
name: luna
version: 0.1.0
model: openai/gpt-5.6-luna
instructions: Play Wordle with the guess action. Use the marks to narrow the word, and stop as soon as it is solved.
```

## Run it offline

```bash
plural benchmark validate wordle
plural run --benchmark wordle --agent word-list
```

```text
benchmark/wordle is valid: version 1.0.0, sha256:7bc988ecca0a4884e7e4307529fa02d580241af366eea7e63ae6e9032b17c5c2
Running benchmark/wordle with word-list (openai/gpt-5.6-luna) locally: 3 trial(s).
  trl_5701d8ede710d21b4970ba8f  crane  succeeded  score=1.000
  trl_1616c550620b8bfbd1c16438  slate  succeeded  score=1.000
  trl_4cb93aab41a7586915bcc295  point  succeeded  score=1.000
Job job_26cbf6d030b5aa44bbddb22f succeeded.
  word-list: mean score 1.000 over 3 trial(s), 3 succeeded
Details: plural job show job_26cbf6d030b5aa44bbddb22f
```

Three Tasks and one Agent make three Trials. The word list contains every secret, so
this Agent always wins; it checks that the project is wired correctly, not how well
anything plays.

## Run it from Python

`run.py` loads the same resources by name and runs the same Benchmark with the same
Agent:

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

`Project.find()` walks up from the directory you give it, or from the current
directory, to find `project.yaml`. Run it with the Python environment you installed
Plural into:

```bash
python run.py
```

```text
crane: score=1.0
slate: score=1.0
point: score=1.0
```

The Python run executes locally like `plural run`, but it is not recorded as a Job: it
does not appear in `plural job list`, and `plural job rerun` cannot repeat it.

## Run it with a model

This calls a model and can incur charges. Store a Plural API key with
`plural auth login --api-key-stdin`, or export `PLURAL_API_KEY` or your own
`OPENAI_API_KEY` for `openai/` models. A browser login is not accepted for model
calls. Then:

```bash
plural run --task crane --model openai/gpt-5.6-luna
plural run --benchmark wordle --agent luna
```

`--model` without `--harness` uses `native`, the same loop the `luna` Agent uses.
The model sees `instruction.md` and the board after each guess. It never sees the
secret, the score, or any reward.

## Read the results

```bash
plural job list
plural job show <job-id>
plural trial show <trial-id>
```

`job show` lists each word with its status and score. `trial show` prints the Verifier
evidence and the path to the Trial's artifacts:

```text
Trial trl_4cb93aab41a7586915bcc295 (local) succeeded
  Job:            job_26cbf6d030b5aa44bbddb22f
  Task:           point
  Score:          1.0
  Artifacts:      /path/to/wordle/.plural/jobs/job_26cbf6d030b5aa44bbddb22f/trials/trl_4cb93aab41a7586915bcc295/executions/0/artifacts
  Logs:           /path/to/wordle/.plural/jobs/job_26cbf6d030b5aa44bbddb22f/trials/trl_4cb93aab41a7586915bcc295/executions/0/logs
  Verifier solved: succeeded score=1.0
    - solved in 4
```

In the `Artifacts` directory, `trajectory.jsonl` has the board after each guess,
`state.json` has the secret and the guess history, `observation.json` has the final
board the Agent saw, and `verifier-results.json` has the score and the `guesses`
sub-score.

A Trial that succeeded can still score 0. That is a missed word, not a crashed run. If
two words score differently, compare their trajectories before changing the model or
the instructions. `plural job rerun <job-id>` repeats a Job with exactly the inputs it
pinned.

## Extend it

- Judge how the Agent played, not only whether it won, with an
  [AgentVerifier](../project/verifiers.md#agentverifier) or a
  [HumanVerifier](../project/verifiers.md#humanverifier).
- Give per-guess credit for training with a `reward()` method or a `@rewarder`; see
  [Rewards](../project/environments.md#rewards). Rewards are recorded on the episode
  and never contribute to the score.

## Push it and run hosted

```bash
plural auth login
plural project init wordle --push
plural benchmark push wordle --with-deps
plural agent push luna --with-deps
plural run --benchmark wordle --agent luna --hosted --follow
```

This needs a Plural account. `project init --push` registers the project, named
`wordle` in `project.yaml`, with a private hosted project and selects it as your
scope. `--with-deps` also pushes the Tasks, Verifier, and Environment the Benchmark
uses. `--hosted` runs the pushed revisions and fails if anything the run uses is not
pushed with identical content. Pushing never makes anything public; sharing is a
separate action in the Plural web app.

Next, build your own project with [Getting started](../getting-started.md#add-resources),
or read [Environments](../project/environments.md) to design a world of your own.
