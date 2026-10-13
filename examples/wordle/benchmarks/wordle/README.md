# wordle

Five Wordle games, each with a fixed secret word. Any word in the Environment's
`words.txt` is a legal guess.

An Agent scores 1 on a game when it finds the word within six guesses and 0 otherwise.
The Benchmark score is the share of games solved. The `guesses` sub-score shows how
quickly each game was solved, but it does not affect ranking.
