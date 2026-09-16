from __future__ import annotations

import io
import json
from pathlib import Path

from plural.environments.runner import main


def test_runner_resets_and_runs_action(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "world.py").write_text(
        "from plural import Environment, Observation, State, action\n"
        "\n"
        "class Board(Observation):\n"
        "    remaining: int = 1\n"
        "\n"
        "class Game(State):\n"
        "    secret: str = ''\n"
        "\n"
        "class World(Environment[Board, Game]):\n"
        "    name = 'world'\n"
        "\n"
        "    def reset(self, *, seed=None, options=None):\n"
        "        super().reset(seed=seed)\n"
        "        self.state = Game(secret='ok', seed=self.state.seed)\n"
        "        self.observation = Board(text='go', remaining=1)\n"
        "        return self.observation, {}\n"
        "\n"
        "    @action\n"
        "    def guess(self, word: str) -> Board:\n"
        "        self.observation = Board(text=word, remaining=0)\n"
        "        return self.observation\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    main(["world.py:World", "reset"])
    reset = json.loads(capsys.readouterr().out)
    assert reset["text"] == "go"
    assert json.loads((tmp_path / "state.json").read_text())["secret"] == "ok"

    monkeypatch.setattr("sys.stdin", io.StringIO('{"word": "slate"}'))
    main(["world.py:World", "guess"])
    guess = json.loads(capsys.readouterr().out)
    assert guess["text"] == "slate"
    assert guess["remaining"] == 0
