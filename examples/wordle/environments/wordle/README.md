# Wordle

## Overview

Guess a hidden five-letter word in six tries. A Task only sets the secret.

## Actions

`guess(word)` is the only move. The result marks each letter: `+` correct, `?` present in the word, `-` absent. A word that is not in `words.txt` is rejected. It does not use a guess, but it does use one of the Trial's turns.

## Word list

`words.txt` holds every accepted word, one per line: the 14,855 guesses Wordle accepts, from [tabatkins/wordle-list](https://github.com/tabatkins/wordle-list) (MIT). `Wordle.words()` reads it once per process. A Task's secret must be in it.

## State

`secret` is the hidden word. A Task sets it with `initial_state`; a blank secret is chosen from `words.txt` using the seed. `guesses`, `remaining`, and `solved` are episode progress. The Agent never sees State. A Verifier does.

## Observations

The Agent sees the board text, how many guesses remain, and whether the word is solved. The secret is not on the Observation.

## Rewards

`reward()` returns per-step credit for training. Rewards never contribute to a score.

## Resources

Files listed under `resources:` in `environment.yaml`, staged into the runtime.

## Runtime

`runtime:` in `environment.yaml` says where the Environment and Agent run.

## Settings

`harness_policy` limits which Agent harnesses may run here. `limits` caps each Trial's
turns, seconds, and cost.
