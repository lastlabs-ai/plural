---
route: /docs/project/environments
title: Environments
order: 30
description: Author typed state, observations, actions, runtime rules, and executable source through the public Environment API.
audience: all
nav: true
nav_group: Project
outcome: You can package a Python action Environment without internal manifests.
---
# Environments

An Environment owns the world in which an Agent acts. Subclass `Environment`,
declare `State` and `Observation`, and mark Agent-facing methods with `@action`.

```python
from plural import Environment, Observation, State, action

class Board(Observation):
    solved: bool = False

class Game(State):
    answer: str = ""

class Puzzle(Environment[Board, Game]):
    name = "puzzle"

    @action
    def guess(self, word: str) -> Board:
        self.observation.solved = word == self.state.answer
        return self.observation
```

Bind source and a command adapter in one call:

```python
environment = Puzzle(runtime=runtime).package(("python", "commands.py"))
```

Plural discovers the source tree, hashes it, derives action commands, and binds
the reset adapter. Users do not call `.definition()`, construct action
manifests, or handle package source records.

`Runtime` is nested on Environment and controls provider, image, compute,
network, filesystem, named secrets, persistence, and placement. Secret values
are never serialized.
