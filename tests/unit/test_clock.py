"""The Environment clock: App time hooks, wait, events, measure every, and the horizon."""

from __future__ import annotations

from typing import Any

import pytest

from plural import App, Environment, Runtime, State, action
from plural.environments.definition import Clock, EnvironmentDefinition
from plural.metrics import MetricSpec
from plural.verifiers import DeterministicVerifier, Step


class Books(State):
    cash: float = 100.0
    stock: int = 10
    sold: int = 0


class Kiosk(App[Books]):
    """Sells a few units at each day's close; a restock arrives half a day later."""

    def reset(self, state: Books | None = None) -> None:
        super().reset(state)
        self.schedule(self.now + 1, "close")

    @action
    def restock(self, units: int) -> str:
        """Buy units at a dollar each."""
        self.state.stock += units
        self.state.cash -= units
        self.schedule(self.now + 0.5, "delivery", text=f"{units} units delivered")
        return f"ordered {units}"

    def advance(self, until: float) -> list[str]:
        out = []
        for event in self.due_events():
            if event["kind"] == "close":
                sold = min(self.state.stock, 2)
                self.state.stock -= sold
                self.state.sold += sold
                self.state.cash += 2 * sold
                out.append(f"Sold {sold}.")
                self.schedule(event["at"] + 1, "close")
            else:
                out.append(event["data"]["text"])
        return out

    def action_duration(self, action: str, arguments: dict[str, Any]) -> float:
        return 0.25


def _cash(step: Step) -> dict[str, float]:
    return {"cash": step.apps["kiosk"].state.cash}


def _environment(**fields: Any) -> Environment:
    return Environment(
        apps=[Kiosk()],
        runtime=Runtime.local(),
        clock={"unit": "day", "start": 1},
        horizon={"sim_time": 5},
        autonomous=True,
        **fields,
    )


def _verifier() -> DeterministicVerifier:
    return DeterministicVerifier(
        name="books",
        measure=_cash,
        measure_every={"sim_time": 1},
        metrics=[MetricSpec(name="cash", kind="running", aggregate="final")],
    )


def test_wait_runs_events_in_order_and_measures_each_day() -> None:
    environment = _environment()
    environment.reset(seed=1, verifiers=[_verifier()])
    assert [item.name for item in environment.definition().actions][-1] == "wait"
    environment.step("restock", units=3)
    observation = environment.step("wait")[0]
    # The delivery half a day after the order wakes the Agent before the close.
    assert observation["text"].startswith("[Day 1.5] 3 units delivered")
    observation = environment.step("wait", until=4)[0]
    assert "[Day 2] Sold 2." in observation["text"]
    assert "[Day 4] Sold 2." in observation["text"]
    report = environment._host.report()
    events = [item for item in report["steps"] if item["kind"] == "event"]
    assert all(item["source"] == "environment" for item in events)
    assert [item["sim_time"] for item in events] == [1.5, 2.0, 3.0, 4.0]
    assert [point["sim_time"] for point in report["metrics"]] == [1.0, 2.0, 3.0, 4.0]
    assert report["metrics"][0]["values"] == {"cash": 100.0}
    assert report["clock"] == {"now": 4.0, "horizon_reached": False}


def test_the_horizon_ends_the_episode_as_truncated() -> None:
    environment = _environment()
    environment.reset(seed=1)
    result = environment.step("wait", until=100)
    assert result[3] is True
    assert environment._host.report()["clock"] == {"now": 6.0, "horizon_reached": True}
    after = environment.step("restock", units=1)
    assert after[3] is True
    assert environment._host.report()["steps"][-1]["action"] == "wait"


def test_agent_paced_actions_take_time() -> None:
    environment = Environment(
        apps=[Kiosk()], runtime=Runtime.local(), clock={"unit": "day", "pacing": "agent_paced"}
    )
    environment.reset(seed=1)
    for _ in range(4):
        environment.step("restock", units=1)
    host = environment._host
    assert host.now == 1.0
    assert any(item["kind"] == "event" for item in host.report()["steps"])


def test_measure_every_steps() -> None:
    environment = _environment()
    verifier = DeterministicVerifier(
        name="books",
        measure=_cash,
        measure_every={"steps": 2},
        metrics=[MetricSpec(name="cash", kind="running", aggregate="final")],
    )
    environment.reset(seed=1, verifiers=[verifier])
    for _ in range(4):
        environment.step("restock", units=1)
    assert [point["step"] for point in environment._host.report()["metrics"]] == [2, 4]


def test_clock_fields_validate_and_leave_old_hashes_alone() -> None:
    plain = Environment(apps=[Kiosk()], runtime=Runtime.local()).definition()
    assert "clock" not in plain.model_dump(mode="json")
    assert "wait" not in [item.name for item in plain.actions]
    with pytest.raises(ValueError, match="clock"):
        Environment(apps=[Kiosk()], runtime=Runtime.local(), autonomous=True).definition()
    with pytest.raises(ValueError, match="clock"):
        Environment(apps=[Kiosk()], runtime=Runtime.local(), horizon={"sim_time": 3}).definition()
    with pytest.raises(ValueError):
        EnvironmentDefinition.model_validate(
            {**plain.model_dump(mode="json"), "checkpoint_every": {"sim_time": 1, "steps": 2}}
        )
    timed = _environment().definition()
    assert timed.finish_allowed is False
    assert _environment(allow_finish=True).definition().finish_allowed is True


def test_clock_labels() -> None:
    assert Clock(unit="day", start=1).label(12) == "Day 12"
    calendar = Clock(unit="hour", start="2026-01-01T09:00:00")
    assert calendar.label(calendar.origin + 2) == "2026-01-01 11:00"
