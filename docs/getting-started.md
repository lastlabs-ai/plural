---
route: /docs/getting-started
title: Quickstart
order: 20
description: "From a new account to a scored Benchmark in about twenty minutes: install Plural, build a small Wordle game, run a model on it, and see every run in the web app."
audience: all
nav: true
nav_group: Start
---
# Quickstart

By the end of this page you'll have built a small Wordle game, scored a model on two
puzzles, and opened the results in the web app. It takes about twenty minutes, and
every block can be pasted as it is. You don't need Docker.

New to words like Environment, Task, and Verifier? [Core concepts](getting-started/concepts.md)
explains them in five minutes. Already have an agent, traces, or a system to test?
[Bring your own work](start/index.md) starts from there instead.

## 1. Create an account and install

1. Sign up at [pluralintel.com](https://pluralintel.com) with email, Google, or GitHub.
   During early access you may be asked to join a waitlist; an invitation from someone
   in your organization lets you in right away.
2. Take the short tour. It ends by creating an **API key**, the secret that lets the
   `plural` command act for you and call models. It is shown once, so keep it in a
   password manager.

Install Plural. You need Python 3.10 or newer:

:::tabs
:::tab pip
```bash
python -m pip install "plural[mcp]>=0.22.1"
```
:::tab uv
```bash
uv tool install "plural[mcp]>=0.22.1"
```
:::

:::details Optional extras
- `plural[mcp]` (above) lets Plural run MCP servers, which new projects use.
- `plural[daytona]` adds the Daytona Runtime.
- `plural[keyring]` stores your credentials in your OS keyring.

To use the Python SDK from a uv project, run `uv add "plural[mcp]>=0.22.1"` inside it.
:::

Then sign in with the key. It is read without being shown, and stored in your user
config folder, never in a project:

```bash
plural auth login --api-key-stdin
```

:::details Other ways to sign in
- **Browser login.** `plural auth login` opens pluralintel.com; approve it there, and
  Plural stores a 30-day key for the account you picked. `plural auth status` checks it.
- **Environment variable.** `export PLURAL_API_KEY=plural_...` works anywhere, which is
  handy in CI.
- **Project keys.** A project key is an API key limited to one project. It can reach
  only that project and can't create new ones.
- **Organizations.** A login acts for one account. To work in another organization,
  select it in the web app and run `plural auth login` again.
:::

Model calls go through Plural's gateway and are billed to your account's credits at the
provider's price. Check your balance under **Credits** in the web app.

## 2. Create a project

A project is a folder that holds everything you build:

```bash
plural project init wordle
cd wordle
plural env init wordle --python --bare
```

`plural env init` wrote a template Environment in `environments/wordle/`. You'll
replace its files in the next two steps. `--bare` leaves out the starter Task and
Verifier it would otherwise add, since you'll write your own.

## 3. Write the game

An **App** is a system the Agent works with, and its **actions** are the moves the
Agent can make. Replace `environments/wordle/environment.py` with:

```python
"""A small Wordle: guess a hidden five-letter word in six tries."""

from plural import App, State, action, initial


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
```

- `Game` is the App's **State**, its private truth. The Agent never sees it.
  `initial()` marks `secret` as a field each Task sets.
- `guess` is an action. Its docstring is the description the model reads, and what it
  returns is all the model sees. Raising `ValueError` tells the model what went wrong.
- The App doesn't grade anything. That is the Verifier's job, in step 6.

## 4. Describe the Environment

An **Environment** is the App plus where it runs. Replace
`environments/wordle/environment.yaml` with:

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

The `local` **Runtime** runs the game on your machine as a trusted subprocess. Step 9
moves it to a cloud sandbox by changing that one line.

## 5. Write two Tasks

A **Task** is one problem to solve. Each Wordle Task is one puzzle, with its own secret:

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

`initial_state` sets the App's `secret`. Because the secret is State, the Agent sees
only the instructions and what each guess returns.

## 6. Write a Verifier

A **Verifier** decides what counts as good work. Create one:

```bash
plural verifier init solved
```

Replace `verifiers/solved/verify.py` with:

```python
"""Score 1 when the secret was guessed, and credit the guess that solved it."""

from plural import Episode, VerifierOutput, Step


def check(episode: Episode) -> VerifierOutput:
    """Read the final State, which the Agent never saw."""
    solved = bool(episode.state.get("solved"))
    used = 6 - int(episode.state.get("remaining", 6))
    return VerifierOutput(score=float(solved), evidence=[f"solved={solved} after {used} guesses"])


def reward(step: Step) -> float:
    """1 on the guess that solves the puzzle."""
    return float(step.current_state["solved"] and not step.previous_state["solved"])
```

In `verifiers/solved/verifier.yaml`, turn on the `reward` function by uncommenting it:

```yaml
check: verify.py:check
reward: verify.py:reward
```

`check` grades what actually happened in the game, not the model's claim that it won.
Its **score** is what a Benchmark ranks on. `reward` runs after every guess and gives
per-step credit for training; it never changes the score.

## 7. Group the Tasks into a Benchmark

A **Benchmark** is a fixed set of Tasks and the rules for ranking results:

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

## 8. Run it

A **Job** runs a Benchmark with one model; each attempt at one Task is a **Trial**.
Every Job runs from your machine:

```bash
plural run --benchmark wordle --model openai/gpt-5.6-luna
```

```text
Running benchmark/wordle with gpt-5.6-luna (openai/gpt-5.6-luna) locally: 2 Trials, 2 at a time (auto: every Trial at once).
  [1/2] trl_a3c4c32fe982f553d6eaf682  crane  succeeded  score=1.000  | 1 succeeded, 0 failed, mean 1.000
  [2/2] trl_7141ed163cc5f72c17a5c3a4  slate  succeeded  score=1.000  | 2 succeeded, 0 failed, mean 1.000
Job job_a9ecd47fc78ca7293e5bc68a succeeded.
  gpt-5.6-luna: mean score 1.000 over 2 Trials, 2 succeeded, coverage 100%
```

The model played both puzzles through the `guess` action, and the Verifier scored each
one. Dig in:

```bash
plural job show <job-id>        # each Trial, its status and score
plural trial show <trial-id>    # the score, the Verifier's evidence, and the logs
plural reward show <trial-id>  # the per-step credit reward gave the winning guess
```

Browse other models with `plural model list`, and add `--dry-run` to see what a run
would do without calling a model. The run is recorded under `.plural/jobs/`, and
`plural job rerun <job-id>` repeats it with exactly the same inputs.

## 9. See it in the web app

So far everything stayed on your machine. To see runs in the web app, and share them
with your team, connect this folder to a private hosted project once, then run with
`--record`:

```bash
plural project init wordle --push
plural run --benchmark wordle --model openai/gpt-5.6-luna --record
```

`--push` registers the folder you're in as a hosted project; nothing local is
overwritten. `--record` still runs everything here. It first pushes anything the run
needs, then records the Job as it runs. Open **Jobs** at
[pluralintel.com](https://pluralintel.com) to watch it: each Trial's score, every
guess the model made, the Verifier's evidence, and what the run cost. Pushing never
makes anything public.

To run the game in a cloud sandbox instead of on your machine, change the
Environment's Runtime and run the same command:

```yaml
runtime:
  provider: daytona
```

The sandboxes start on Plural's Daytona account, so you don't need one of your own, and
are billed to your credits by the resources they use. See
[Track runs and run in the cloud](platform/runs.md).

## Where you are now

You have a Benchmark you can rerun on any model with
`plural run --benchmark wordle --model <model> --record`. Next:

- **[Wordle tutorial](tutorials/wordle.md)** builds the full game, with the real word
  list, a saved Agent, and the Python SDK.
- **[Bring your own work](start/index.md)** starts from traces you already have, or
  from a system such as an MCP server.
- **[Publish to the Hub](platform/publish.md)** shares a Benchmark and its leaderboard.
- **[CLI guide](cli/evaluation.md)** lists every command.
