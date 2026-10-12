# Wordlebench

Wordlebench asks an Agent to solve seven Wordle tasks with the `wordle` Environment. The `solved` Verifier scores each task 1 when the hidden word is guessed and 0 otherwise. The Benchmark rank is the mean of those scores. Per-guess rewards are recorded for training and do not affect the rank.

Every task accepts the same 14,855-word list, the Environment's `words.txt`, and none of them shows it. The task names do not reveal the hidden word. A high score means the Agent used the marks to narrow the word. A solved task can still have used every guess.
