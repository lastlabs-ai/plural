"""Long runs: the run journal, interrupted Trials, personas, peers, and context restore."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from plural import App, Environment, Runtime, State, action
from plural.apps.host import AppHost
from plural.changes import ForkPoint, apply_change
from plural.checkpoints import _compactions
from plural.execution.journal import STALE_SECONDS, RunJournal, interrupted
from plural.sim import Persona, PersonaUnavailable, answer, call_key


class Ledger(State):
    cash: float = 50.0


class Bank(App[Ledger]):
    name = "bank"


class Mail(State):
    replies: list[str] = []


calls: list[int] = []


def _script(messages: Any) -> str:
    calls.append(len(messages))
    return f"quote #{len(calls)}"


class Supplier(App[Mail]):
    name = "supplier"
    persona = Persona("acme", "You sell widgets at $2.", script=_script)

    @action
    def ask(self, message: str) -> str:
        """Ask the supplier something."""
        reply = self.persona.reply(self, message)
        self.state.replies = [*self.state.replies, reply]
        return reply

    @action
    def buy(self, units: int) -> str:
        """Buy widgets, paid from the bank."""
        self.peer("bank").state.cash -= 2 * units
        return f"bought {units}"


def _environment() -> Environment:
    return Environment(
        apps=[Bank(), Supplier()],
        runtime=Runtime.local(),
        clock={"unit": "day", "start": 1},
        checkpoint_every={"steps": 2},
    )


def _host(tmp_path: Path) -> AppHost:
    host = AppHost(_environment(), tmp_path)
    host.reset(seed=3)
    return host


def test_a_peer_change_is_recorded_with_the_step(tmp_path: Path) -> None:
    host = _host(tmp_path)
    host.step("buy", {"units": 5})
    bank = [item for item in host.report()["states"] if "bank" in (item.get("state") or {})]
    assert bank[-1]["step"] == 1
    assert bank[-1]["state"]["bank"]["cash"] == 40.0
    with pytest.raises(RuntimeError, match="outside an App host"):
        Supplier().peer("bank")


def test_personas_are_recorded_seeded_and_replayed_after_a_restore(tmp_path: Path) -> None:
    calls.clear()
    host = _host(tmp_path)
    first = host.step("ask", {"message": "price?"})["observation"]["text"]
    host.step("ask", {"message": "and for 100?"})
    report = host.report()
    recorded = report["personas"]
    assert [item["mode"] for item in recorded] == ["scripted", "scripted"]
    assert recorded[0]["output"] == first == "quote #1"
    assert recorded[0]["persona"] == "acme" and recorded[0]["cost_usd"] in (0.0, None)
    # A run checkpoint every two steps.
    assert [item["step"] for item in report["run_checkpoints"]] == [2]
    progress = host.progress({"steps": 1, "personas": 1})
    assert len(progress["steps"]) == len(report["steps"]) - 1
    assert [item["output"] for item in progress["personas"]] == ["quote #2"]

    # Restored at step 0 with the recorded calls, the same question is answered from
    # the record, not the script.
    opening = report["states"][0]
    replay = AppHost(_environment(), tmp_path / "replay")
    replay.restore(
        states=opening["state"], rng=opening.get("rng"), step=0, turns=0, personas=recorded
    )
    before = len(calls)
    again = replay.step("ask", {"message": "price?"})
    assert again["observation"]["text"] == "quote #1"
    assert len(calls) == before
    assert replay.report()["personas"][-1]["mode"] == "replayed"


def test_a_persona_without_a_model_or_script_says_so() -> None:
    persona = Persona("silent", "Say nothing.")
    with pytest.raises(PersonaUnavailable, match="script"):
        answer(persona, persona.messages("hi"), 1, environ={})
    assert call_key(persona, [{"role": "user", "content": "a"}], 1) != call_key(
        persona, [{"role": "user", "content": "a"}], 2
    )


def test_the_journal_keeps_progress_and_finds_the_latest_checkpoint(tmp_path: Path) -> None:
    trial = tmp_path / "trl_1"
    journal = RunJournal.of(trial)
    journal.start(0)
    added = journal.append(
        {
            "steps": [{"step": 1}, {"step": 2}],
            "states": [{"step": 0}, {"step": 1}, {"step": 2}],
            "metrics": [{"sim_time": 1.0, "values": {"x": 1.0}}],
            "checkpoints": [{"step": 2, "sim_time": 3.0}],
            "clock": {"now": 3.0},
        }
    )
    assert added == [{"step": 2, "sim_time": 3.0}]
    assert journal.cursors()["steps"] == 2
    journal.append({"checkpoints": [{"step": 4, "sim_time": 5.0}]})
    # Step 4's State hasn't reached the journal, so step 2 is the latest it can resume from.
    assert journal.latest() == {"step": 2, "sim_time": 3.0}
    assert journal.state()["clock"] == {"now": 3.0}

    episode = [
        {"sequence": 1, "kind": "model.call", "usage": {"cost_usd": 0.01}},
        {"sequence": 2, "kind": "environment.step", "info": {"step": 1}},
        {"sequence": 3, "kind": "model.call", "usage": {"cost_usd": 0.02}},
        {"sequence": 4, "kind": "environment.step", "info": {"step": 2}},
        {"sequence": 5, "kind": "model.call", "usage": {"cost_usd": 0.04}},
    ]
    journal.episode("\n".join(json.dumps(item) for item in episode).encode())
    assert journal.spent_through(1) == pytest.approx(0.01)
    assert journal.spent_through(2) == pytest.approx(0.03)

    assert not interrupted(trial)
    assert interrupted(trial, now=time.time() + STALE_SECONDS + 1)
    result = trial / "executions" / "0" / "result.json"
    result.parent.mkdir(parents=True)
    result.write_text("{}")
    assert not interrupted(trial, now=time.time() + STALE_SECONDS + 1)


def test_a_context_change_restores_what_a_compaction_dropped() -> None:
    opening = [
        {"role": "system", "content": "You run a machine."},
        {"role": "user", "content": "Suppliers: harbor-wholesale."},
    ]
    records = [
        {"kind": "model.call", "sequence": 1, "messages": opening},
        {"kind": "context.compaction", "turn": 9, "strategy": "summarize", "summary": "s"},
    ]
    compactions = _compactions(records)
    assert compactions and compactions[0]["opening"] == opening
    assert _compactions(records[:1]) is None

    messages = [opening[0], {"role": "user", "content": "Summary: sold snacks."}]
    point = ForkPoint(
        payload={"mode": "restore"},
        messages=[dict(item) for item in messages],
        observation=None,
        rendered="",
        environment={},
        compactions=compactions,
    )
    apply_change("context", point)
    assert point.messages == [opening[0], opening[1], messages[1]]

    plain = ForkPoint(
        payload={"mode": "restore"},
        messages=messages,
        observation=None,
        rendered="",
        environment={},
    )
    with pytest.raises(ValueError, match="no compaction"):
        apply_change("context", plain)
