---
route: /docs/project/environments
title: Environments
order: 30
description: Author typed state, observations, actions, runtime rules, and executable source through the public Environment API.
audience: all
nav: true
nav_group: Build
outcome: You can package a Python action Environment without internal manifests.
---
# Environments

An Environment is the executable world shared by many Tasks. It owns typed
State and Observation, actions, Runtime, resources, limits, rendering, and
optional Rewarders. It does not own Tasks, Verifiers, Agents, or Job mode.

```python
from plural import Environment, Observation, State, action, hidden

class Board(Observation):
    text: str = ""
    solved: bool = False

class Game(State):
    answer: str = hidden("")
    guesses: int = 0

class Puzzle(Environment[Board, Game]):
    name = "puzzle"
    version = "1.0.0"

    @action
    def guess(self, word: str) -> Board:
        self.state.guesses += 1
        self.observation.solved = word == self.state.answer
        self.observation.text = "solved" if self.observation.solved else "try again"
        return self.observation
```

`State` persists world data. `Observation` is the projection sent to the Agent.
`hidden(...)` marks evaluator-only State in the generated schema; do not copy
those values into an Observation, action result, model message, or artifact.

Implement the Gymnasium-shaped lifecycle when defaults are insufficient:

```python
def reset(self, *, seed=None, options=None):
    super().reset(seed=seed)
    self.state = Game(answer="crane", seed=self.state.seed)
    self.observation = Board(text="Guess the word.")
    return self.observation, {}

def terminated(self) -> bool:
    return self.observation.solved
```

The Job or Harness calls `reset()` and `step()`. The Agent calls only methods
marked `@action`. Never decorate `reset` or `step`.

## Make actions executable

Python methods are authoring declarations. Package them with a command adapter
that receives the action name in argv and JSON parameters on stdin:

```python
environment = Puzzle(runtime=runtime).package(
    ("python", "commands.py"),
    source="environment",
)
```

The adapter must preserve State in its working directory and write
`state.json`, `observation.json`, and optional `view.json`. `.package(...)`
hashes the source tree and derives command actions. Do not author internal
manifests or call private compilation methods.

Use `view()` for a JSON-safe operator rendering. `Observation.render()` controls
the text shown to the policy. They serve different audiences.

## Configure the owned components

Pass these to the constructor:

- `runtime`: where execution runs and which controls must be enforced.
- `resources`: data, application, or file descriptors owned by the world.
- `secrets`: names and targets only—never values.
- `guardrails`: plain-language world rules.
- `harness_policy`: limits on optional Harnesses and their capabilities.
- `limits`: `max_turns=8`, `max_seconds=120`, optional `max_cost_usd`.
- `overview`, `readme`, and `metadata`: human context and indexing data.

Read [Runtime](runtime.md) before running untrusted code and
[Environment components](environment-components.md) for actions, resources,
Rewarders, rendering, and lifecycle details.
