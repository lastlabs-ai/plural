# wordle

Guess a hidden five-letter word in six tries.

## Actions

- `guess(word)`: guess one word from the dictionary. The board marks each letter `+`
  (right place), `?` (in the word, elsewhere), or `-` (not in the word).

## State

A Task picks the secret with `initial_state.secret`. The secret lives on State, so the
Agent never sees it; it only sees the board.

The episode ends when the word is solved or six guesses are used.
