# wordle

Three Wordle puzzles, each with a fixed secret word from a five-word dictionary.

An Agent scores 1 on a puzzle when it solves it within six guesses and 0 otherwise.
The Benchmark score is the share of puzzles solved. The `guesses` sub-score shows how
efficiently each puzzle was solved, but it does not affect ranking.
