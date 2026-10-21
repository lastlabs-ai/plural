---
route: /docs/tutorials/wordle
title: Wordle
order: 115
description: Walk through a Wordle project that uses every core concept, an App that keeps the secret on State, a Verifier that scores and rewards, an Agent, and a Benchmark, and run it with a model from the CLI or Python.
audience: all
nav: true
nav_group: Tutorials
outcome: You can run a model on a five-game Wordle Benchmark from the CLI or Python, and read every message it sent.
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

- seen how each piece of a Plural project fits together,
- had a real model play a five-game exam, from the command line and from Python,
- read the results, down to every message the model sent.

## Before you start

You need Plural installed; see [Install](../getting-started.md#1-create-an-account-and-install). The project is
`examples/wordle` in the [Plural repository](https://github.com/lastlabs-ai/plural).
Copy it anywhere and run the commands from inside it:

```bash
git clone https://github.com/lastlabs-ai/plural.git
cp -R plural/examples/wordle wordle
cd wordle
```

Exploring the files needs nothing. Running a game calls a model, so it needs a Plural
account; see [Run it](#run-it).

## What is in the project

Every [core concept](../getting-started/concepts.md) appears once:

| Concept | In this project |
| --- | --- |
| **App** | The game, `Wordle`, which keeps the secret word on its State |
| **Environment** | `wordle`: the game, the word list, and where it runs |
| **Task** | `crane`, `slate`, `point`, `storm`, and `nymph`: one secret word each |
| **Verifier** | `solved`: scores each game and rewards each guess |
| **Agent** | `luna`: a model and the instructions it plays by |
| **Harness** | `native`, Plural's built-in loop, which `luna` plays with |
| **Benchmark** | `wordle`: the five games, ranked by score |
| **Job** and **Trial** | Each run you start, and each game played in it |

On disk:

```text
environments/wordle/          environment.yaml, environment.py, README.md, words.txt
tasks/<word>/                 task.yaml, instruction.md, for crane, slate, point, storm, nymph
verifiers/solved/             verifier.yaml, verify.py
agents/luna/                  agent.yaml
benchmarks/wordle/            benchmark.yaml, README.md
run.py                        the same run from the Python SDK
```

`project.yaml`, `plural.lock`, and `pyproject.toml` sit at the top, as in every
project.

### The game is one App

An [App](../concepts/apps.md) is one system the AI works with. Here it is the game,
in `environments/wordle/environment.py`, and it separates what the game knows from
what the AI sees:

- **State** is the game's private truth: the secret word and the guesses so far.
- What an action **returns** is all the AI sees: the guess, its marks, and how many
  guesses are left.

```python
class Game(State):
    secret: str = initial(
        "",
        description="The hidden five-letter word. Empty picks one from words.txt using the seed.",
        max_length=5,
        pattern=r"^([a-z]{5})?$",
    )
    guesses: list[str] = Field(default_factory=list)
    found: str = "....."
    solved: bool = False
```

`initial()` marks `secret` as a field a Task may set. That is how each Task chooses its
word. `found` records the letters placed so far, such as `cr..e`; the grader uses it to
reward progress.

The game has one move, `guess`:

```python
class Wordle(App[Game]):
    """Guess a hidden five-letter word in six tries."""

    @action
    def guess(
        self,
        word: Annotated[str, Field(min_length=5, max_length=5, pattern=r"^[a-z]{5}$")],
    ) -> str:
        """Guess one word. + is correct, ? is elsewhere in the word, - is absent."""
        if word not in self.words():
            raise ValueError(f"{word!r} is not in the word list")
        ...
        return f"{word}  {' '.join(GLYPHS[mark] for mark in scored)}\n{status}"

    def terminated(self) -> bool:
        return self.state.solved or len(self.state.guesses) >= GUESSES
```

The docstring is the description the AI reads, and the `word` limits are part of the
action's schema, so the model sees them too. A word that isn't in the list raises
`ValueError`: the AI is told why and can try again. The game ends when `terminated()`
sees the word solved or no guesses left.

The marks are Wordle's colors written as symbols: `+` is the right letter in the right
place (green), `?` is in the word somewhere else (yellow), and `-` is not in the word
(gray). After guessing `point` against the secret `point`, the AI sees:

```text
point  + + + + +
solved
```

:::details The rest of the App: reset and the board view
`reset` starts each game, and what it returns is the first thing the AI sees. A Task
that leaves `secret` blank gets a word picked from `words.txt` using the Trial's seed.

`view()` returns the board for the run viewer: each guess and its marks, never the
secret. See [Display views](../project/environments.md#display-views).
:::

### The Environment

`environments/wordle/environment.yaml` names the App, the files the world starts with,
where it runs, and the limits on each game:

```yaml
name: wordle
version: 1.0.0
description: Guess a hidden five-letter word. Each guess is marked correct, present, or absent.
overview: Six guesses. The secret stays on State, and the Agent only sees what each guess returns.
python: environment.py:Wordle
readme: README.md
resources:
  - words.txt
runtime:
  provider: local
limits:
  max_turns: 8
  max_seconds: 120
```

- `words.txt` holds the 14,855 guesses Wordle accepts. The App reads it from its own
  folder. Listing it under `resources` also puts it in `/workspace/resources`, where a
  Harness that reads files, such as a coding agent, can look words up.
- `local` runs the game directly on your machine, so the project runs anywhere. It is
  not a sandbox: use `provider: docker` to run each game in a container.
- `max_turns: 8` leaves room for two refused words on top of six guesses.

### Each Task sets one secret

A Task is one game. `tasks/crane/task.yaml`:

```yaml
name: crane
version: 1.0.0
instructions: instruction.md
environment: wordle
verifiers:
  - solved
initial_state:
  secret: crane
```

The other four differ only in their name and secret. Because the secret is State, the
AI never sees it. It sees `instruction.md` and what each guess returns, nothing else.

### The Verifier scores each game

The Verifier is the grader. `solved` is a deterministic Verifier (a
`DeterministicVerifier` in Python): a small piece of code that checks the answer
exactly. Its `check`, in `verifiers/solved/verify.py`, reads the game's final State,
which the AI never saw:

```python
def check(episode: Episode) -> VerifierOutput:
    """Score 1 when the secret was found and 0 otherwise. Report the guesses used."""
    guesses = len(episode.state["guesses"])
    solved = episode.state["solved"]
    return VerifierOutput(
        score=float(solved),
        scores={"guesses": float(guesses)},
        evidence=[f"solved in {guesses}" if solved else f"unsolved after {guesses}"],
    )
```

The grader looks at what actually happened in the game, not at the AI's claim that it
won. `score` is what the Benchmark ranks on. The `guesses` sub-score shows how quickly
each game was solved, but it does not affect ranking.

:::details Rewards: credit for each guess, for training
The same Verifier also hands out **rewards**: credit on single guesses that a training
system can learn from. `verifier.yaml` names all three functions:

```yaml
name: solved
version: 1.0.0
kind: deterministic
check: verify.py:check
reward: verify.py:reward
hindsight: verify.py:fewer_guesses
```

`reward` runs after every guess. It sees the State before and after, and gives 0.2 for
each letter the guess newly put in place:

```python
def reward(step: Step) -> float:
    """0.2 for each letter a guess newly puts in place, and -0.1 for a refused word."""
    if step.error:
        return -0.1
    before = step.previous_state["found"].count(".")
    after = step.current_state["found"].count(".")
    return round(0.2 * (before - after), 2)
```

`fewer_guesses` runs once the game is over, when you can judge things no single guess
shows, and credits the winning guess more the sooner it came:

```python
def fewer_guesses(trial: HindsightTrial):
    """Once the game is won, credit the winning guess more the fewer guesses it took."""
    guesses = trial.steps("guess")
    if trial.score and guesses:
        yield trial.credit(guesses[-1]["event_id"], round(1.0 - 0.1 * (len(guesses) - 1), 2))
```

Both go to the Trial's reward ledger, `rewards.jsonl`. They never change the score, and
the AI never sees them. To try a changed reward on games you already played, run
`plural verifier try solved --job JOB_ID`; see
[Label stored Trials](../running/training.md#label-stored-trials).
:::

### The Agent

An Agent is a contestant: a model and the instructions it plays by.
`agents/luna/agent.yaml`:

```yaml
name: luna
version: 1.0.0
model: openai/gpt-5.6-luna
instructions: >
  You play Wordle. Call guess with one five-letter word at a time. A reply marks
  each letter: + correct, ? in the word somewhere else, - absent. Use every mark
  to narrow the next guess.
```

It names no Harness, so it plays with `native`, Plural's built-in loop. A **Harness**
is the loop between the model and the game: it shows the model the instructions and
what each action returned, offers it `guess` as a tool, and takes the action the model
picks. It only ever passes along what the AI is allowed to see: never the secret, the
score, or a reward.

:::details Use another loop, or your own model
- `harness: claude-code` or `harness: codex` runs a well-known agent loop instead, and
  a Python `Harness` subclass runs one you write; see
  [Harnesses](../project/harnesses.md).
- `endpoint:` points the Agent at your own OpenAI-compatible server instead of the
  Plural gateway, and needs no Plural key; see [Agents](../project/agents.md).
:::

### The Benchmark

`benchmarks/wordle/benchmark.yaml` is the exam: the five games, and how results are
ranked:

```yaml
name: wordle
version: 1.0.0
tasks: [crane, slate, point, storm, nymph]
scoring:
  metric: Games solved
  aggregation: weighted_mean
  score_range: [0.0, 1.0]
  success_threshold: 1.0
  agent_failure: zero
  infrastructure_error: exclude
```

The Agent's score is the share of games it solved. A game lost to a crash on your side,
rather than the Agent's, is left out and reported separately.

## Run it

Running a game calls a model through the Plural gateway, which bills it at the
provider's price: a few cents for this Benchmark. Sign in once, which stores a Plural
API key for you:

```bash
plural auth login
```

Validate the Benchmark, which also checks every Task, Verifier, and Environment it
uses, then run it with `luna`:

```bash
plural benchmark validate wordle
plural run --benchmark wordle --agent luna
```

You should see one line per game as it finishes. Your ids will differ, the games may
finish in a different order, and a model may not play the same way twice:

```text
Running benchmark/wordle local with luna (openai/gpt-5.6-luna) locally: 5 Trials, 5 at a time (auto: every Trial at once).
  [1/5] trl_49f1abde184c29875cccba31  crane  succeeded  score=1.000  | 1 succeeded, 0 failed, mean 1.000
  [2/5] trl_506e8fe955a473c5392b07d8  slate  succeeded  score=1.000  | 2 succeeded, 0 failed, mean 1.000
  [3/5] trl_1e9c501ec2ba6f578be6d8fe  nymph  succeeded  score=1.000  | 3 succeeded, 0 failed, mean 1.000
  [4/5] trl_1f2adcdea70605ea8f835b89  storm  succeeded  score=1.000  | 4 succeeded, 0 failed, mean 1.000
  [5/5] trl_10723e07ab67be6e92f42fe1  point  succeeded  score=1.000  | 5 succeeded, 0 failed, mean 1.000
Job job_d9dbdde2f7b0e81cad12f704 succeeded.
  luna: mean score 1.000 over 5 Trials, 5 succeeded
Details: plural job show job_d9dbdde2f7b0e81cad12f704
```

The whole run is one **Job**, and each game is a **Trial**: five Tasks and one Agent
make five Trials. To try a single game, or another model without an Agent file, run
`plural run --task crane --model openai/gpt-5.6-luna`.

> **Good to know:** *succeeded* means the game ran to the end; the score says how well
> the Agent did. A game the Agent loses still succeeds, with a score of 0. A crash
> would be `failed`.

## Run it from Python

Everything the command line does, you can also do from Python. `run.py` loads the same
pieces by name and runs the same Benchmark:

```python
from pathlib import Path

from plural import Job
from plural.project import Project, Workspace

if __name__ == "__main__":
    workspace = Workspace(Project.find(Path(__file__).parent))
    benchmark = workspace.get("benchmark", "wordle")
    agent = workspace.get("agent", "luna")
    result = Job(benchmark, agents=[agent]).run()
    for trial in result.trials:
        print(f"{trial.receipt.task_pin.name}: score={trial.score}")
```

Run it with the Python environment you installed Plural into:

```bash
python run.py
```

```text
crane: score=1.0
slate: score=1.0
nymph: score=1.0
storm: score=1.0
point: score=1.0
```

> **Good to know:** The Python run is not recorded as a Job, so it does not appear in
> `plural job list`.

## Read the results

Three commands take you from the overview down to one game:

```bash
plural job list
plural job show <job-id>
plural trial show <trial-id>
```

`trial show` prints the grader's evidence and where the game's files are kept:

```text
Trial trl_1e9c501ec2ba6f578be6d8fe (local) succeeded
  Job:            job_d9dbdde2f7b0e81cad12f704
  Task:           nymph
  Score:          1.0
  Artifacts:      /path/to/wordle/.plural/jobs/job_d9dbdde2f7b0e81cad12f704/trials/trl_1e9c501ec2ba6f578be6d8fe/executions/0/artifacts
  Logs:           /path/to/wordle/.plural/jobs/job_d9dbdde2f7b0e81cad12f704/trials/trl_1e9c501ec2ba6f578be6d8fe/executions/0/logs
  Verifier solved: succeeded score=1.0
    - solved in 3
```

`trajectory.json` in the Artifacts folder is the conversation, in the chat format most
tools already read: each message's `role` and `content`, the model's tool calls, and
what each call returned, beside the run's `status`, `time_elapsed`, and `finalized`.
After the instructions, this game went:

```json
{"role": "assistant", "tool_calls": [{"function": {"name": "guess", "arguments": "{\"word\":\"crane\"}"}}]}
{"role": "tool", "content": "crane  - - - ? -\n5 left"}
{"role": "assistant", "tool_calls": [{"function": {"name": "guess", "arguments": "{\"word\":\"night\"}"}}]}
{"role": "tool", "content": "night  + - - ? -\n4 left"}
{"role": "assistant", "tool_calls": [{"function": {"name": "guess", "arguments": "{\"word\":\"nymph\"}"}}]}
{"role": "tool", "content": "nymph  + + + + +\nsolved"}
```

The reward ledger, `rewards.jsonl`, tells the same story guess by guess: `night`
placed the `n` (0.2), `nymph` placed the other four letters (0.8), and once the game
was won, `fewer_guesses` credited that guess with 0.8.

If two games score differently, read the messages before you change the model or the
instructions. `plural job rerun <job-id>` repeats a Job with exactly the inputs it
pinned.

:::details Everything else in the Artifacts folder
- `atif-trajectory.json`: the same turns in ATIF, with each call's tokens and cost.
- `episode.jsonl` and `steps.jsonl`: each guess, and what the AI saw after it.
- `apps.json` and `state.json`: the game's State, which is what the Verifier read.
- `states.jsonl`: the State after every guess, so you can replay rewards later.
- `rewards.jsonl`: the reward ledger.
- `view.json`: the board the run viewer draws.
- `result.json`: the score, the `guesses` sub-score, and the evidence.
:::

## Push it and run hosted

To see the games in the web app, connect the project to a private hosted project and
record the run with `--record`. This needs a Plural account:

```bash
plural auth login
plural project init wordle --push
plural run --benchmark wordle --agent luna --record
```

`project init --push` registers the project with a new private hosted project.
`--record` still plays every game here. It first pushes the Benchmark, its Tasks,
Verifier, and Environment, and the Agent, then records each game in the web app under
**Jobs** as it is played.

> **Good to know:** Pushing never makes anything public. Sharing is a separate action
> in the Plural web app.

## Where to go next

- Start an Environment of your own with [Create an Environment](../start/index.md).
- Read [Environments](../project/environments.md) to design a world of your own.
- Read [Several Agents in one Task](../project/multi-agent.md) to have several Agents
  share one game.
- Shape rewards for training with [Reward each step](../project/verifiers.md#reward-each-step).
