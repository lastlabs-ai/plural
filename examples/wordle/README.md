# Wordle

Wordle as a Plural project: an Agent guesses a hidden five-letter word, and a Verifier
scores whether it found it.

```text
environments/wordle/          the game: one App that keeps the secret on State
tasks/crane ... nymph/        five games, one secret word each
verifiers/solved/             scores a game, rewards each guess
agents/luna/                  a model on Plural's built-in loop
benchmarks/wordle/            the five games, ranked by score
run.py                        the same run from Python
```

```bash
plural auth login
plural run --benchmark wordle --agent luna
```

The tutorial walks through every file: <https://pluralintel.com/docs/tutorials/wordle>.
