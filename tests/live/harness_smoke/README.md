# Harness smoke test

Each built-in Harness (the native loop, Claude Code, Codex and Hermes) runs one Task
that it can pass only by writing `smoke.txt`. Every model call must go through the
Plural gateway. Run it with `scripts/harness_smoke.sh`.
