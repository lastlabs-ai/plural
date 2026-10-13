# Wordle

Guess a hidden five-letter word in six tries. A Task only sets the secret.

## Actions

`guess(word)` is the only move. The result marks each letter: `+` correct, `?` in the
word somewhere else, `-` absent. A word that is not in `words.txt` is refused. It does
not use a guess, but it does use one of the Trial's turns.

## State

`secret` is the hidden word; a Task sets it with `initial_state`, and a blank one is
picked from `words.txt` using the seed. `guesses`, `found` (the letters placed so far,
such as `cr..e`), and `solved` are the game's progress. The Agent never sees State. A
Verifier does.

## What the Agent sees

What `guess` returns: the word, its marks, and how many guesses are left or that it is
solved. The secret never appears in it.

## Word list

`words.txt` holds the 14,855 guesses Wordle accepts, from
[tabatkins/wordle-list](https://github.com/tabatkins/wordle-list) (MIT). It is also an
Environment resource, so a Harness can read it from `/workspace/resources`.
