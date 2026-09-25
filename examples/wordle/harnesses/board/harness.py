"""A Wordle loop that remembers the board and only shows the model that record."""

import json

from plural import Harness, HarnessResult


class BoardHarness(Harness):
    name = "board"
    description = "Tracks Wordle marks and tells the model what each letter has shown."

    def run(self, task, agent, environment):
        """Play one game. The model sees the board record, never the reward or the secret."""
        observation = environment.reset()
        board = _Board()
        board.note(observation)
        messages = [
            {"role": "system", "content": agent.instructions},
            {"role": "user", "content": task.instructions},
            {"role": "user", "content": board.prompt()},
        ]
        trajectory = []
        for turn in range(6):
            completion = agent.complete(messages, tools=environment.tools())
            trajectory.append({"turn": turn, "type": "model", "text": completion.text})
            if not completion.tool_calls:
                return HarnessResult(response=completion.text, trajectory=tuple(trajectory))
            messages.append(
                {
                    "role": "assistant",
                    "content": completion.text,
                    "tool_calls": list(completion.tool_calls),
                }
            )
            done = False
            for call in completion.tool_calls:
                function = call["function"]
                arguments = json.loads(function.get("arguments") or "{}")
                step = environment.step(function["name"], **arguments)
                board.note(step.observation)
                trajectory.append(
                    {
                        "turn": turn,
                        "type": "action",
                        "name": function["name"],
                        "arguments": arguments,
                        "observation": step.observation,
                    }
                )
                # The tool result is the harness's board, not the raw step reward.
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": board.prompt(),
                    }
                )
                done = step.terminated or step.truncated or board.solved
            if done:
                return HarnessResult(response=board.prompt(), trajectory=tuple(trajectory))
        return HarnessResult(response=board.prompt(), trajectory=tuple(trajectory))


class _Board:
    """Letter knowledge derived only from observations the Agent is allowed to see."""

    def __init__(self) -> None:
        self.rows: list[str] = []
        self.correct = ["."] * 5
        self.present: set[str] = set()
        self.absent: set[str] = set()
        self.remaining = 6
        self.solved = False
        self.opening = ""

    def note(self, observation: object) -> None:
        text = _text(observation)
        if not self.rows and not text[:1].isalpha():
            self.opening = text
        for line in text.splitlines():
            parts = line.split()
            marks = "".join(parts[1:6])
            if len(parts) == 6 and len(parts[0]) == 5 and set(marks) <= {"+", "?", "-"}:
                word = parts[0]
                self.rows.append(f"{word}  {' '.join(marks)}")
                for index, (letter, mark) in enumerate(zip(word, marks, strict=True)):
                    if mark == "+":
                        self.correct[index] = letter
                        self.present.discard(letter)
                    elif mark == "?" and self.correct[index] != letter:
                        self.present.add(letter)
                    elif mark == "-" and letter not in self.correct and letter not in self.present:
                        self.absent.add(letter)
            elif line == "solved":
                self.solved = True
            elif line.endswith(" left") and line.split()[0].isdigit():
                self.remaining = int(line.split()[0])
        record = observation if isinstance(observation, dict) else {}
        if record.get("solved") is True:
            self.solved = True
        if isinstance(record.get("remaining"), int):
            self.remaining = record["remaining"]

    def prompt(self) -> str:
        pattern = "".join(self.correct)
        present = " ".join(sorted(self.present)) or "none"
        absent = " ".join(sorted(self.absent)) or "none"
        history = "\n".join(self.rows) or "no guesses yet"
        return "\n".join(
            (
                self.opening,
                "Board:",
                history,
                f"Pattern: {pattern}",
                f"Present elsewhere: {present}",
                f"Absent: {absent}",
                f"Guesses left: {self.remaining}",
                "Solved." if self.solved else "Not solved yet.",
            )
        )


def _text(observation: object) -> str:
    if isinstance(observation, dict):
        value = observation.get("text")
        return value if isinstance(value, str) else json.dumps(observation)
    return str(observation)
