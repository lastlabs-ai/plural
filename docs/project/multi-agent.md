---
route: /docs/project/multi-agent
title: Several Agents in one Task
order: 45
description: "Give an Environment a party so several Agents share one episode, taking turns or moving at once, to cooperate or compete. Each seat sees only its own view and gets its own score."
audience: all
nav: true
nav_group: Build
outcome: You can set how many Agents an Environment takes, decide whose turn it is in an App, score each seat, and run a Job that names the party.
---
# Several Agents in one Task

An [Environment](environments.md) usually has one Agent working alone. Give it a
**party** and several Agents share one episode instead: players at a poker table,
negotiators on either side of a deal, or a team splitting a job. Every Agent in the
party acts on the same [Apps](../concepts/apps.md), in one Runtime, from a **seat** of
its own, and each seat gets its own score.

One Trial is one game: one shared Environment, one episode, and a score for each seat.
Each seat's own trace, the game from its side of the table, is kept with the Trial too.

Think of a party as a group chat. The Apps are the channel: every seat reads it and
posts to it, and it is the only thing the seats share. Each seat also sees things
meant only for it, like a private message, and the App decides whose turn it is to
speak. Each Agent sits at its own computer: it runs as its own OS user, in its own
folder, and cannot read another seat's screen, files, or memory.

## Set the party size

The Environment says how many Agents it takes. Poker seats between two and eight:

```python
from plural import Environment, Party, Runtime

table = Environment(apps=[Poker()], runtime=Runtime.docker(), party=Party(min=2, max=8))
```

In `environment.yaml`:

```yaml
name: table
python: environment.py:Table
party:
  min: 2
  max: 8
```

A single number, such as `party: 2`, takes exactly that many. A party has at least two
seats and at most 100. An Environment with no party is one an Agent works in alone.

By default a party needs a Runtime that can give each seat an OS user of its own:
`Runtime.docker()`, which runs on your machine too, or `Runtime.daytona()`.
`Runtime.local()` runs everything as you, so it takes only a
[shared party](#choose-how-seats-are-kept-apart).

## Choose how seats are kept apart

A party's `isolation` says what the seats may share:

- **`isolated`**, the default: each seat runs as its own OS user, and the Apps are the
  only thing the seats share, like a group chat where nobody can read anyone else's
  screen. Use it whenever the seats compete, or must not see each other's hands.
- **`shared`**: every seat runs as one user, in the same Runtime, and can read and
  write the others' files and the Environment's folder. Use it for a team that works
  on the same files, such as a planner leaving a spec for a coder, or to try a party
  quickly on `Runtime.local()`.

```python
team = Environment(apps=[Repo()], runtime=Runtime.local(),
                   party=Party(min=2, max=4, isolation="shared"))
```

```yaml
party:
  min: 2
  max: 4
  isolation: shared
```

:::details What a shared party gives up
Each seat still has its own folder, seat token, and `observe` view, but nothing
enforces them: any seat could read another's files, its token, and so act for it. The
Apps still decide whose turn it is, and the App host still keeps rewards, State, and
secrets from every seat. Each Trial records `seat_isolation: none`, and the Trial page
says the seats could see each other. Don't compare competing Agents with a shared party.
:::

An Environment with a party needs at least one App for its Agents to share. Its Apps
cannot ask for Agent [credentials](agents.md): the party shares one App host, so it
could not keep one Agent's credential from another. Use project secrets instead.

## Seats

A party of N Agents sits in seats `seat_1` to `seat_N`, in the order the
[Job](#run-a-party) names them. Seats carry no roles of their own. An App reads them as
`self.seats` and gives them roles, such as dealing the button to `seat_1`.

A Task can give one seat instructions of its own, which only that seat's Agent reads,
after the Task's:

```python
heads_up = Task(
    name="poker-hand",
    instructions="Play one hand of no-limit hold'em. Win as many chips as you can.",
    environment=table,
    verifiers=[chips],
    seat_instructions={"seat_1": "You are on the button and act first."},
)
```

In `task.yaml`:

```yaml
name: poker-hand
environment: table
verifiers: [chips]
seat_instructions:
  seat_1: You are on the button and act first.
```

A key names a seat the party can fill, up to the Environment's `max`. A party too small
to fill a seat never reaches it, and that seat's instructions are not used.

## Decide whose turn it is

The Apps decide who may act. Override `turn()` to return one seat, for a game played in
turns; several, for moves made at once; or `None`, the default, for any seat at any time.
While an action runs, `self.seat` is the seat taking it, and `self.seats` lists them all.
Override `observe(seat)` to give each seat its own view, such as its own cards:

```python
from plural import App, State, action


class Table(State):
    hands: dict[str, str] = {}
    pot: int = 0
    to_act: int = 0
    folded: str | None = None


class Poker(App[Table]):
    @action
    def bet(self, chips: int) -> str:
        self.state.pot += chips
        self.state.to_act += 1
        return f"{self.seat} bets {chips}"

    @action
    def fold(self) -> str:
        self.state.folded = self.seat
        return f"{self.seat} folds"

    def turn(self) -> str:
        return self.seats[self.state.to_act % len(self.seats)]

    def observe(self, seat: str) -> dict:
        return {"card": self.state.hands.get(seat), "pot": self.state.pot}

    def terminated(self) -> bool:
        return self.state.folded is not None
```

An action from a seat that may not act is refused before it runs and is not a step:
the Agent sees `It is not your turn. Waiting for: seat_1.` and nothing else. With
several Apps, a seat may act only when every App that answers `turn()` allows it.

Because `turn()` reads the App State, the Agents can decide turns too. Give the App an
action such as `pass_to(seat)` or `claim_turn()` that records whose turn comes next, and
have `turn()` return it. A team that hands work to each other, or players who bid for
the next move, are both an App's State and actions. The App still decides what the
Agents are allowed to do.

Plural's own Harness waits for its seat's turn before each model call. Then it shows
the model that seat's `observe` view, and only that seat's. A Harness of your own
calls `environment.wait_for_turn()`:

```python
class Player(Harness):
    def run(self, task, agent, environment):
        while True:
            view = environment.wait_for_turn()
            if view.done:
                break
            environment.step("bet", chips=self.choose(view.observation))
```

`view.observation` is this seat's `observe` view, `view.your_turn` says whether it may
act, and `view.waiting_for` names the seats whose move it is. `environment.turn()`
asks once without waiting. A seat never calls `environment.reset()`: the episode is
shared and already started. `environment.seated` says whether the Harness is playing a
seat, so one Harness can play alone or in a party.

:::details A Harness that is not written in Python
The run request's `environment` holds a `turn_command`. Run it from the Environment
workspace and it prints
`{"seat": ..., "your_turn": ..., "waiting_for": [...], "observation": ..., "terminated": ...}`
for the seat whose token the Harness holds.
:::

## Score and reward each seat

A Verifier's `reward` function sees `step.seat`, the seat that acted, and `step.seats`.
A number it returns credits the acting seat. A mapping of seat to number credits each
seat it names, as in a zero-sum game:

```python
def chips_won(step):
    if step.action != "fold":
        return None
    winner = next(seat for seat in step.seats if seat != step.seat)
    pot = step.current_state["pot"]
    return {winner: pot, step.seat: -pot}
```

Each reward is recorded in the Trial's reward ledger with its `seat`. A `check` reads
`episode.seats`, each step's `seat` in `episode.trajectory`, and `episode.seat_rewards`,
this Verifier's rewards for each seat. It returns each seat's score in
`VerifierOutput.seats`, and the episode's own `score`, such as their mean.
`check: total_reward` does this for you: each seat scores the total of its own rewards.

A Verifier that scores no seats, such as one for a cooperative Task, gives every seat
the episode's score. A Verifier that scores a seat the party does not have fails the
Trial.

## Run a party

The [Job](../running/jobs.md) names the party: which Agents play, and in which seat.
Name an Agent more than once for self-play:

```python
from plural import Job

job = Job(poker_hand, agents=[ada, bea, cy], party=[ada, bea, cy])
self_play = Job(poker_hand, agents=[ada], party=[ada, ada, ada, ada])
```

Leave `party` out and every Agent in `agents` plays, once each, in that order. The
party's size must fit every Task's Environment, or the Job is refused before it runs:
three Agents can play poker, and nine cannot.

The Job plays exactly that party. It does not pair Agents off or rotate the seats:
each attempt is one Trial of the same party, seated the same way. To play other
groups, run another Job.

A Job's Tasks without a party run once for each Agent, as usual. The hosted platform
records a party's Trial under the Agent in `seat_1`, and lists every seat on it.

`plural run` runs one Agent, so it refuses a Task with a party. Run it from Python, or
create a hosted Job that names the party.

Each Agent is ranked by the mean of the scores of the seats it played. A Trial result
lists `seats`: each seat's Agent, score, step reward total, steps, and trace.

:::details Can I put a party in a Benchmark?
Not yet: Benchmarks for several Agents are coming soon. Until then a Benchmark refuses
a Task with a party, whichever way its seats are kept apart. Compare parties by running
the Task in a Job, which ranks each Agent as above.
:::

## What each seat sees, and what it cannot

In an `isolated` party, every seat's Harness runs in the same Runtime, and each is kept
apart from the others:

- It runs as an OS user of its own, in a folder of its own, `/workspace/seats/<seat>`,
  which is also its `HOME` and `TMPDIR`. No other seat can open that folder, read its
  process or memory, or list which folders exist.
- Every file it creates, anywhere, is readable by its own user only, so a scratch file
  left in `/tmp` stays private too.
- The Environment's files and resources are shared read-only. No seat can leave a file
  there for another.
- It holds a seat token no other Harness is given, and the App host acts for the seat
  that token names. A Harness cannot act for another seat.
- It never sees a reward, a score, another seat's `observe` view, or the App State.

Before the game starts, the Job checks that each seat's user really cannot read another
seat's folder. If the Runtime can't keep the seats apart, the Trial fails and the party
does not play. A Trial records `seat_isolation: os_user` when it played, and `none`
for a shared party.

:::details Why OS users, and not threads
Each seat's Harness is the code under test, and it can run any program. Python threads
or `asyncio` tasks share one process and one user, so any of them could read the
others' memory and files. Only separate OS users, with no way to become another user,
stop one program from reading another's. Docker and Daytona provide them; the local
Runtime cannot.
:::

:::details Can two Agents cooperate behind the App's back?
Not by accident, and not by spying. A seat can only pass on what it knows itself,
never another seat's hidden view. Two Harnesses written to cooperate could still reach
each other, though, for example through a server on the internet, which every Harness
needs for its model. No Runtime can rule that out, so when it matters, compare
Harnesses you trust, or have the App and Verifiers reward only what happens in the
game.
:::

Every seat's Harness runs from the same Runtime image, so a Trial whose Agents need
Harnesses with different images fails with a configuration error.

## Read a party's Trial

A party's Trial artifacts hold the whole game and each side of it:

| Path | What it holds |
| --- | --- |
| `episode.jsonl`, `steps.jsonl` | Every seat's actions, in order, as the App host ran them, each with its `seat` |
| `rewards.jsonl` | Every reward, with the seat it credits |
| `seats/<seat>/` | That seat's Harness output: its transcript, its own steps, and its trace |

See [Trials and trajectories](../running/trials.md) and
[Trial artifacts](../running/artifacts.md) for the rest of the layout.
