<p align="center">
  <a href="https://pluralintel.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lastlabs-ai/plural/main/.github/assets/logo-dark.svg">
      <img alt="Plural" src="https://raw.githubusercontent.com/lastlabs-ai/plural/main/.github/assets/logo-light.svg" width="300">
    </picture>
  </a>
</p>

<h3 align="center">The task is the unit of intelligence. Find which model is best at yours.</h3>

<p align="center">
  <a href="https://pypi.org/project/plural/"><img alt="PyPI" src="https://img.shields.io/pypi/v/plural?color=6a30a8"></a>
  <a href="https://pypi.org/project/plural/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/plural"></a>
  <a href="https://github.com/lastlabs-ai/plural/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/lastlabs-ai/plural/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
</p>

<p align="center">
  <a href="https://pluralintel.com/docs/getting-started">Quickstart</a> |
  <a href="https://pluralintel.com/docs">Docs</a> |
  <a href="https://github.com/lastlabs-ai/plural/tree/main/examples">Examples</a> |
  <a href="https://pluralintel.com">pluralintel.com</a>
</p>

---

Plural is a framework for building evals that optimize agent performance on the tasks
you care about. It discovers which models work best on your task and routes work to
those agents.

- **Local or hosted.** Keep your evals in a folder and run them on your machine, or
  store them in a hosted project at [pluralintel.com](https://pluralintel.com) to track
  and compare every run.
- **Runs where you need it.** On your machine, in Docker, or in remote sandboxes such as
  [Daytona](https://www.daytona.io) (`pip install "plural[daytona]"`).

## Get started

You need Python 3.10 or newer and an account at [pluralintel.com](https://pluralintel.com),
which model calls go through.

```bash
pip install "plural[mcp]"
plural auth login

plural project init my-eval && cd my-eval
plural env init support-desk
plural run --task support-desk-first --model openai/gpt-5.6-luna
```

```text
Running task/support-desk-first with gpt-5.6-luna (openai/gpt-5.6-luna) locally: 1 Trial, 1 at a time (auto: every Trial at once).
  [1/1] trl_6523ca3f8db536eaa894d2fb  support-desk-first  succeeded  score=1.000  | 1 succeeded, 0 failed, mean 1.000
Job job_168352e303f3330932a452c6 succeeded.
  gpt-5.6-luna: mean score 1.000 over 1 Trial, 1 succeeded, coverage 100%
```

That's a full measurement: `plural env init` wrote a small support desk (an
**Environment**), one assignment in it (a **Task**), and the code that grades it (a
**Verifier**), and `plural run` scored a model on it. Try another model with
`--model`, see what happened with `plural job show <job-id>`, then make it yours: the
run first lists each `PLURAL-TODO` in the new files, an example for you to replace.

## Or write it in Python

An App is a class whose actions are the agent's tools:

```python
# wordle.py
from plural import App, Environment, Runtime, State, action, initial

class Game(State):
    secret: str = initial("", description="The hidden word.")
    guesses: int = 0
    solved: bool = False

class Wordle(App[Game]):
    """Guess a hidden five-letter word."""

    @action
    def guess(self, word: str) -> str:
        """Guess a word. + is right, ? is elsewhere, - is absent."""
        secret = self.state.secret
        self.state.guesses += 1
        self.state.solved = word == secret
        return " ".join("+" if a == b else "?" if a in secret else "-" for a, b in zip(word, secret))

    def terminated(self) -> bool:
        return self.state.solved or self.state.guesses >= 6

environment = Environment(name="wordle", apps=[Wordle()], runtime=Runtime.local())
```

A Task sets the hidden State, and a Verifier, kept in its own file so the agent can't
read it, scores the result:

```python
# run.py
from plural import Agent, DeterministicVerifier, Episode, Job, Task, VerifierOutput
from wordle import environment

def solved(episode: Episode) -> VerifierOutput:
    return VerifierOutput(score=float(episode.state["solved"]))

task = Task(
    name="crane",
    instructions="Find the hidden five-letter word.",
    environment=environment,
    initial_state={"secret": "crane"},
    verifiers=[DeterministicVerifier(name="solved", check=solved)],
)
result = Job(task, agents=[Agent(model="openai/gpt-5.6-luna")]).run()  # after plural auth login
print(result.aggregates[0].mean_score)
```

For a training loop, step the same Environment yourself, Gym-style:

```python
observation, info = environment.reset(initial_state={"secret": "crane"}, seed=0)
observation, reward, terminated, truncated, info = environment.step("guess", word="trace")
# {'text': '- + + ? +'} 0.0 False False
```

## The vocabulary

| | |
| --- | --- |
| **App** | One system the agent works with. Its actions are the agent's tools; its State stays hidden. |
| **Environment** | Apps, plus where they run and the episode's limits. |
| **Task** | One assignment in an Environment, with its starting State. |
| **Verifier** | The grader: `check` scores the finished episode; `reward` credits each step. |
| **Agent** | A model, its instructions, and the harness that drives it. |
| **Benchmark** | A versioned set of Tasks and the rules for ranking results. |
| **Job / Trial** | A run of Agents on a Task or Benchmark / one attempt, with its full record. |

## See it in the web app

Connect your project folder to a private hosted project once, then add `--record` to
any run to see its Trials, trajectories, and costs at [pluralintel.com](https://pluralintel.com),
and to rank models on a Benchmark's leaderboard. Jobs still run on your machine, and
nothing is ever made public.

```bash
plural project init my-eval --push         # from inside my-eval
plural run --task support-desk-first --model openai/gpt-5.6-luna --record
```

Runs are recorded once the starter's `PLURAL-TODO` examples are replaced.

## Learn more

- [Quickstart](https://pluralintel.com/docs/getting-started): build and benchmark Wordle in ten minutes.
- [Start from your own system](https://pluralintel.com/docs/start): an MCP server, an API, or traces.
- [Verifiers](https://pluralintel.com/docs/project/verifiers) and [training](https://pluralintel.com/docs/running/training): scores, step rewards, and RL.
- [Multi-agent Tasks](https://pluralintel.com/docs/project/multi-agent): seats, turns, and shared worlds.
- [Python SDK](https://pluralintel.com/docs/sdk/evaluation) and [CLI reference](https://pluralintel.com/docs/cli/evaluation).
- [Examples](https://github.com/lastlabs-ai/plural/tree/main/examples), including a support queue that runs offline with a scripted agent.
- [Changelog](CHANGELOG.md).

## Development

```bash
uv sync --group dev --group docs
uv run ruff check . && uv run mypy src
uv run pytest tests/unit tests/contract
uv run python scripts/check_docs.py
```

## License

[Apache-2.0](LICENSE)
