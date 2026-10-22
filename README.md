<p align="center">
  <a href="https://pluralintel.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/lastlabs-ai/plural/main/.github/assets/logo-dark.svg">
      <img alt="Plural" src="https://raw.githubusercontent.com/lastlabs-ai/plural/main/.github/assets/logo-light.svg" width="300">
    </picture>
  </a>
</p>

<h3 align="center">Build the environment. Write the tasks. Benchmark and train agents on your real work.</h3>

<p align="center">
  <a href="https://pypi.org/project/plural/"><img alt="PyPI" src="https://img.shields.io/pypi/v/plural?color=6a30a8"></a>
  <a href="https://pypi.org/project/plural/"><img alt="Python" src="https://img.shields.io/pypi/pyversions/plural"></a>
  <a href="https://github.com/lastlabs-ai/plural/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/lastlabs-ai/plural/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
</p>

<p align="center">
  <a href="https://pluralintel.com/docs/getting-started">Quickstart</a> ·
  <a href="https://pluralintel.com/docs">Docs</a> ·
  <a href="https://pluralintel.com/docs/tutorials/wordle">Tutorial</a> ·
  <a href="examples/">Examples</a> ·
  <a href="https://pluralintel.com">pluralintel.com</a>
</p>

---

Plural is a Python SDK and CLI for turning the systems your agents work with into
**environments**, writing **tasks** in them, and finding out which model or agent does
that work best, with the evidence behind every score.

- **Any system becomes an environment.** Wrap a Python class, an MCP server, an
  OpenAPI service, or a recorded trace as an App. The agent sees only what its actions
  return.
- **Grade what happened, not what the agent claims.** Verifiers read the App's hidden
  State after the episode, and can reward every step for training.
- **Reproducible by default.** Every run pins each input by content hash, so
  `plural job rerun` repeats it exactly.
- **Runs where you need it.** On your machine, in Docker, or in cloud sandboxes, with
  any model in the catalog, Claude Code, Codex, or your own harness.
- **Benchmarks and training from one setup.** The same Task feeds a leaderboard and an
  RL loop, and several agents can share one Task to cooperate or compete.

## Install

```bash
pip install "plural[mcp]"
```

Python 3.10 or newer. Model calls go through the Plural gateway, so a live run needs
an API key from [pluralintel.com](https://pluralintel.com): `plural auth login`.

## Try it in 30 seconds

The [support queue example](examples/first-project/) has a scripted Agent, so it runs
offline with no account:

```bash
git clone --depth 1 https://github.com/lastlabs-ai/plural && cd plural/examples/first-project
plural run --benchmark support-triage --agent scripted
```

```text
Running benchmark/support-triage with scripted (openai/gpt-5.6-luna) locally: 3 Trials, 3 at a time (auto: every Trial at once).
  [1/3] trl_e346797c26bf78918a0ccd64  ticket-3  succeeded  score=1.000  | 1 succeeded, 0 failed, mean 1.000
  [2/3] trl_eabb98d92a791437296f8a41  ticket-2  succeeded  score=1.000  | 2 succeeded, 0 failed, mean 1.000
  [3/3] trl_d180e73c8fa30bc6cae755b5  ticket-1  succeeded  score=1.000  | 3 succeeded, 0 failed, mean 1.000
Job job_e7bbd52f5a400c1409488cef succeeded.
  scripted: mean score 1.000 over 3 Trials, 3 succeeded, coverage 100%
```

`plural job show <job-id>` lists each Trial, and `plural trial show <trial-id>` shows the
Verifier's evidence and the full record.

## Build your own

From the command line, a project is a folder of small, versioned resources:

```bash
plural project init my-eval && cd my-eval
plural env init support-desk                     # an Environment, a starter Task, a Verifier
plural run --task support-desk-first --model openai/gpt-5.6-luna
```

Or in Python. An App is a class whose actions are the agent's tools:

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
from plural import Agent, Client, DeterministicVerifier, Episode, Job, Task, VerifierOutput
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
result = Job(task, agents=[Agent(model="openai/gpt-5.6-luna")], client=Client()).run()
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

Connect a folder to a private hosted project once, then add `--record` to any run to
watch its Trials, trajectories, and costs in [pluralintel.com](https://pluralintel.com).
Every Job still runs from your machine, and pushing never makes anything public.

```bash
plural project init my-eval --push
plural run --task support-desk-first --model openai/gpt-5.6-luna --record
```

## Learn more

- [Quickstart](https://pluralintel.com/docs/getting-started): build and benchmark Wordle in ten minutes.
- [Start from your own system](https://pluralintel.com/docs/start): an MCP server, an API, or traces.
- [Verifiers](https://pluralintel.com/docs/project/verifiers) and [training](https://pluralintel.com/docs/running/training): scores, step rewards, and RL.
- [Multi-agent Tasks](https://pluralintel.com/docs/project/multi-agent): seats, turns, and shared worlds.
- [Python SDK](https://pluralintel.com/docs/sdk/evaluation) and [CLI reference](https://pluralintel.com/docs/cli/evaluation).
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
