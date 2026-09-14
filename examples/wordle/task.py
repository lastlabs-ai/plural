from verifier import solved

from environment import environment
from plural import Task
from wordle import WORDS

task = Task(
    name="easy-01",
    instructions=(
        f"Guess the hidden five-letter word from: {', '.join(WORDS)}. "
        "Call guess one word at a time and stop when solved."
    ),
    environment=environment,
    verifiers=[solved],
    initial_state={"secret": "slate"},
)
