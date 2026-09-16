---
route: /docs/tutorials/wordle
title: Wordle
order: 115
description: Build a Wordle Environment, score it with a DeterministicVerifier, run five Tasks, and read the results.
audience: all
nav: true
nav_group: Tutorials
outcome: You can build, run, and interpret a five-Task Wordle evaluation from either the SDK or YAML and the CLI.
---
# Wordle

The Environment hides a five-letter word. The agent calls `guess`, gets letter marks, and tries again until it solves the word or uses six guesses. A `DeterministicVerifier` scores 1 when the board is solved.

This walkthrough builds that Environment, a verifier, five fixed Tasks (one per word), a Job, and then shows how to read the results. Choose the Python SDK or YAML and the CLI.

## Build and run

=== "Python SDK"


    Save this as `project.py`. The Environment keeps the secret on State. Each Task sets that secret through `initial_state`, so `reset` must preserve it.

    ```python
    from pydantic import Field

    from plural import (
        Agent,
        Benchmark,
        DeterministicVerifier,
        Episode,
        Environment,
        Job,
        Observation,
        Runtime,
        State,
        Task,
        VerifierOutput,
        action,
    )

    WORDS = ("crane", "slate", "audio", "point", "heart")


    class Board(Observation):
        remaining: int = 6
        solved: bool = False


    class Game(State):
        secret: str = ""
        remaining: int = 6
        solved: bool = False
        guesses: list[str] = Field(default_factory=list)


    class Wordle(Environment[Board, Game]):
        name = "wordle"
        overview = "Guess a hidden five-letter word in six tries."

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            secret = self.state.secret
            self.state.remaining = 6
            self.state.solved = False
            self.state.guesses = []
            self.observation = Board(text="6 guesses left", remaining=6)
            if secret not in WORDS:
                raise ValueError("Task initial_state.secret must be one of the dictionary words")
            self.state.secret = secret
            return self.observation, {}

        @action
        def guess(self, word: str) -> Board:
            word = word.strip().lower()
            if word not in WORDS:
                raise ValueError(f"{word!r} is not in the dictionary")
            leftover = list(self.state.secret)
            marks = ["-"] * 5
            for i, letter in enumerate(word):
                if letter == self.state.secret[i]:
                    marks[i] = "+"
                    leftover[i] = ""
            for i, letter in enumerate(word):
                if marks[i] == "+" or letter not in leftover:
                    continue
                marks[i] = "?"
                leftover[leftover.index(letter)] = ""
            self.state.guesses.append(word)
            self.state.remaining -= 1
            self.state.solved = word == self.state.secret
            status = "solved" if self.state.solved else f"{self.state.remaining} left"
            self.observation = Board(
                text=f"{word}  {' '.join(marks)}\n{status}",
                remaining=self.state.remaining,
                solved=self.state.solved,
            )
            return self.observation

        def terminated(self) -> bool:
            return self.state.solved or self.state.remaining <= 0


    def solved(episode: Episode) -> VerifierOutput:
        return VerifierOutput(reward=float(bool(episode.observation.get("solved"))))


    environment = Wordle(runtime=Runtime.local())
    verifier = DeterministicVerifier(name="solved", check=solved)
    tasks = [
        Task(
            name=word,
            instructions=f"Guess the hidden word from: {', '.join(WORDS)}. Call guess and stop when solved.",
            environment=environment,
            verifiers=[verifier],
            initial_state={"secret": word},
        )
        for word in WORDS
    ]
    agent = Agent(
        model="openai/gpt-5.6-luna",
        instructions="Use the letter marks to rule out words. Stop when solved.",
    )
    benchmark = Benchmark(name="wordle", version="1.0.0", tasks=tasks)
    job = Job(benchmark, agents=[agent])
    ```

    `+` is the right letter in the right place, `?` is the right letter elsewhere, and `-` is absent. The verifier reads the completed Episode and ignores the agent's claim that it finished.

    Validate, then run:

    ```bash
    plural validate project.py:job
    plural run project.py:job --dry-run
    plural auth login
    plural run project.py:job
    ```

    Or call `job.run()` after `plural auth login`. Five Tasks × one Agent is five Trials.

=== "YAML and CLI"


    The Environment and check are still Python. YAML points at those objects and names the five Tasks.

    `wordle.py` — same `Wordle` class as the SDK tab, constructed later by YAML.

    `verify.py`:

    ```python
    from plural import Episode, VerifierOutput


    def solved(episode: Episode) -> VerifierOutput:
        return VerifierOutput(reward=float(bool(episode.observation.get("solved"))))
    ```

    `environment.yaml`:

    ```yaml
    kind: environment
    python: wordle.py:Wordle
    name: wordle
    runtime:
      provider: local
      allow_unsafe_local: true
    ```

    `verifier.yaml`:

    ```yaml
    kind: deterministic
    name: solved
    check:
      python: verify.py:solved
    ```

    `tasks/crane.yaml` — copy this for `slate`, `audio`, `point`, and `heart`, changing `name` and `secret`:

    ```yaml
    kind: task
    name: crane
    instructions: Guess the hidden word from crane, slate, audio, point, heart. Call guess and stop when solved.
    environment: ../environment.yaml
    verifiers:
      - ../verifier.yaml
    initial_state:
      secret: crane
    ```

    `agent.yaml`:

    ```yaml
    kind: agent
    name: feedback-first
    model: openai/gpt-5.6-luna
    instructions: Use the letter marks to rule out words. Stop when solved.
    ```

    `benchmark.yaml`:

    ```yaml
    kind: benchmark
    name: wordle
    version: 1.0.0
    tasks:
      - tasks/crane.yaml
      - tasks/slate.yaml
      - tasks/audio.yaml
      - tasks/point.yaml
      - tasks/heart.yaml
    ```

    `job.yaml`:

    ```yaml
    kind: job
    source: benchmark.yaml
    agents:
      - agent.yaml
    ```

    ```bash
    plural validate job.yaml
    plural run job.yaml --dry-run
    plural auth login
    plural run job.yaml
    ```

## Interpret the results

```bash
plural job list
plural job show JOB_ID
plural trial list JOB_ID
plural trial watch TRIAL_ID --job JOB_ID
```

`job show` prints mean reward, cost, and latency. `trial list` shows each word. Reward 1 means that word was solved. Reward 0 means the agent used its guesses without matching the secret.

Open `.plural/jobs/JOB_ID/trials/TRIAL_ID/` when a score is surprising:

- **Trajectory:** each guess and the marks it received.
- **State:** the hidden word and guess history.
- **Observation:** the final board the agent saw.
- **Verifier results:** the solved check and its evidence.

A completed Trial can still score 0. That is a missed word, not a crashed run. If two words score differently, compare their trajectories before changing the model or instructions.
