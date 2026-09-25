# Wordlebench

Wordlebench asks an Agent to solve seven Wordle tasks with the `wordle` Environment. The `solved` Verifier scores each task 1 when the hidden word is guessed and 0 otherwise. The Benchmark rank is the mean of those scores. Per-guess rewards are recorded for training and do not affect the rank.

Three tasks show a five-word list, two show a ten-word list, and two show no list. The task names do not reveal the hidden word. A high score means the Agent used the marks to narrow the word. It does not measure open-ended vocabulary beyond this Environment's dictionary, and a solved task can still have used every guess.
