from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from plural.harness import interface
from plural.harness.deadline import STOP_VARIABLE, call_timeout, episode_deadline
from plural.harness.episode import EpisodeRecorder
from plural.harness.interface import HarnessAgent


class _Response:
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()


def _gateway(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    timeouts: list[float] = []

    def _urlopen(request: object, timeout: float = 0) -> _Response:
        timeouts.append(timeout)
        return _Response()

    monkeypatch.setenv("PLURAL_GATEWAY_URL", "http://gateway.test/v1")
    monkeypatch.setattr(interface.urllib.request, "urlopen", _urlopen)
    return timeouts


def test_a_model_call_may_wait_as_long_as_the_episode_has_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeouts = _gateway(monkeypatch)
    agent = HarnessAgent({"model": "local/qwen"}, deadline=time.monotonic() + 1800)

    assert agent.complete([{"role": "user", "content": "hi"}]).text == "ok"
    assert 1790 < timeouts[0] <= 1800


def test_a_call_after_the_deadline_fails_without_waiting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    timeouts = _gateway(monkeypatch)
    recorder = EpisodeRecorder(tmp_path / "episode.jsonl")
    agent = HarnessAgent({"model": "local/qwen"}, recorder=recorder, deadline=time.monotonic() - 1)

    with pytest.raises(TimeoutError, match="max_seconds"):
        agent.complete([{"role": "user", "content": "hi"}])
    assert timeouts == []
    assert "max_seconds" in (tmp_path / "episode.jsonl").read_text()


def test_the_deadline_is_max_seconds_capped_by_the_stop_the_engine_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(STOP_VARIABLE, raising=False)
    assert call_timeout(episode_deadline({"max_seconds": 3600})) == pytest.approx(3600, abs=1)
    assert call_timeout(episode_deadline()) == pytest.approx(600, abs=1)
    monkeypatch.setenv(STOP_VARIABLE, "900")
    assert call_timeout(episode_deadline({"max_seconds": 3600})) == pytest.approx(900, abs=1)
    assert call_timeout(episode_deadline()) == pytest.approx(900, abs=1)
