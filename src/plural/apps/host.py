"""Run one episode across an Environment's Apps.

The App host owns everything that happens behind the action boundary: it
resets every App from the Task's initial state, routes each exposed action to
its App, runs the Environment's ``on_step`` hook, calls each of the Task's
Verifiers' ``reward`` hooks, and reports snapshots for their ``check`` hooks. It
returns one step envelope per call.

The Agent sees only :meth:`AppHost.agent_view` of an envelope: the observation,
and the error when the action rejected its input. Rewards, snapshots, step
info, and views are bookkeeping kept in the host's step log, which only the Job
reads back, with :meth:`AppHost.report`.
"""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import importlib.util
import json
import math
import random
import sys
import time
import traceback
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from plural.apps.base import App, observation_payload
from plural.apps.workspace import BUNDLE_FILE, WorkspaceSnapshots
from plural.common import described
from plural.environments.definition import WAIT_ACTION
from plural.snapshots import Snapshotter
from plural.verifiers import Step, StepTask

if TYPE_CHECKING:
    from plural.environments.env import Environment

STEP_PROTOCOL = "plural-step-v1"
STATES_FILE = "states.jsonl"
STEPS_FILE = "steps.jsonl"
AGENT_FIELDS = (
    "protocol",
    "kind",
    "app",
    "action",
    "observation",
    "rendered",
    "terminated",
    "truncated",
)
"""The envelope fields the Agent may see. Everything else stays in the host."""
_AGENT_INFO = ("step", "error")
EPISODE_OVER = "The episode is over; the App host takes no more actions."


class AppHandle:
    """What ``Environment.on_step`` may do with one App."""

    def __init__(self, host: AppHost, app: App[Any]) -> None:
        self._host = host
        self._app = app

    @property
    def name(self) -> str:
        """The App's name."""
        return self._app.name

    @property
    def state(self) -> Any:
        """The App's typed state, for a Python App."""
        return self._app.state

    def snapshot(self) -> Any:
        """Read the App's current state.

        Returns:
            The App's snapshot, or ``None`` when it cannot report one.
        """
        return self._app.snapshot() if self._app.has_snapshot() else None

    def call(self, action: str, **arguments: Any) -> Any:
        """Run one of the App's actions as an effect, not an Agent action.

        Returns:
            The action's observation.
        """
        result = self._app.call(action, arguments)
        self._host._effects.append(
            {"app": self._app.name, "action": action, "arguments": arguments}
        )
        return result


class AppView:
    """What a Verifier's ``reward`` hook may read of one App: never an action that writes.

    ``state`` and ``snapshot()`` are copies, so a hook that changes them changes
    nothing the App, the Agent, or a ``check`` will see.
    """

    def __init__(self, host: AppHost, app: App[Any]) -> None:
        self._host = host
        self._app = app

    @property
    def name(self) -> str:
        """The App's name."""
        return self._app.name

    @property
    def state(self) -> Any:
        """A copy of the App's typed state, for a Python App."""
        return copy.deepcopy(self._app.state)

    def snapshot(self) -> Any:
        """Read the App's current state.

        Returns:
            The App's snapshot, or ``None`` when it cannot report one.
        """
        return self._host._snapshot(self._app)

    def query(self, action: str, /, **arguments: Any) -> Any:
        """Call one of the App's read-only actions.

        Returns:
            The action's observation.
        """
        return self._host.query(self._app.name, action, arguments)


@dataclass(frozen=True)
class RewardHook:
    """A Task Verifier's ``reward`` or ``measure`` hook, loaded where the Apps run.

    A ``measure`` hook names the running metrics it may return.
    """

    name: str
    version: str
    fn: Callable[[Step], Any]
    hook: Literal["reward", "measure"] = "reward"
    metrics: tuple[str, ...] = ()
    every: Mapping[str, float] | None = None
    """For ``measure``: run each period, ``{"sim_time": x}`` or ``{"steps": n}``,
    instead of after every step."""


def load_reward_hooks(root: Path, entries: Sequence[Mapping[str, Any]]) -> list[RewardHook]:
    """Import each Verifier's ``reward`` and ``measure`` hooks from the files the Job staged.

    Each entry names a Verifier, its version, its hook as ``file.py:function``,
    and the folder holding its source, relative to ``root``. A ``measure``
    entry also says so in ``hook`` and lists its running metrics.

    Returns:
        The hooks, in the Task's order.

    Raises:
        ValueError: When a hook's file or function is missing.
    """
    loaded: list[RewardHook] = []
    for entry in entries:
        name = str(entry["name"])
        folder = (root / str(entry["dir"])).resolve()
        file_name, _, function_name = str(entry["python"]).rpartition(":")
        path = folder / file_name
        if not path.is_file():
            raise ValueError(f"Verifier {name!r}: its reward hook file {file_name} is missing")
        module_name = f"_plural_verifier_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Verifier {name!r}: cannot import {file_name}")
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(folder))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(folder))
        function: Any = module
        for part in function_name.split("."):
            function = getattr(function, part, None)
            if function is None:
                raise ValueError(f"Verifier {name!r}: {file_name} has no {function_name}")
        loaded.append(
            RewardHook(
                name=name,
                version=str(entry.get("version") or ""),
                fn=function,
                hook="measure" if entry.get("hook") == "measure" else "reward",
                metrics=tuple(str(item) for item in entry.get("metrics") or ()),
                every=dict(entry["every"]) if isinstance(entry.get("every"), Mapping) else None,
            )
        )
    return loaded


class AppHost:
    """Episode state for one Environment's Apps in one process."""

    def __init__(
        self,
        environment: Environment,
        workspace: str | Path | None = None,
        *,
        verifiers: Sequence[RewardHook] = (),
        task: StepTask | None = None,
        private_state: bool = False,
        seats: Sequence[str] = (),
        agent_workspace: str | Path | None = None,
        snapshot_store: str | Path | None = None,
        snapshot_mib: int = 512,
        snapshot_ignore: Sequence[str] = (),
    ) -> None:
        # When the Harness shares this workspace, the full App State, which may hold
        # a secret, must not sit in a file it can read: keep it in memory and hand it
        # to the Job over the control socket instead.
        self.private_state = private_state
        self.environment = environment
        self.definition = environment.definition()
        self.apps: dict[str, App[Any]] = {item.name: item for item in environment.apps}
        self.routes = {item.name: (item.app, item.action) for item in self.definition.actions}
        self.workspace = Path(workspace) if workspace is not None else None
        if self.workspace is not None:
            for app in self.apps.values():
                app.workspace = self.workspace
        self.seats = tuple(seats)
        if len(set(self.seats)) != len(self.seats):
            raise ValueError("seats must have different names")
        for app in self.apps.values():
            app.seats = self.seats
        self.verifiers = tuple(verifiers)
        self.task = task or StepTask()
        self.initial: dict[str, Any] = {}
        self.turns = 0
        self.steps = 0
        self.started = False
        self.finished = False
        self.opening: dict[str, Any] | None = None
        self._effects: list[dict[str, Any]] = []
        self._recorded: dict[str, Any] = {}
        self._states: list[dict[str, Any]] = []
        self._log: list[dict[str, Any]] = []
        self._last_observation: dict[str, Any] = {}
        self._last_view: dict[str, Any] | None = None
        self._hidden: tuple[str, ...] = ()
        self._acting: str | None = None
        self._metrics: list[dict[str, Any]] = []
        self._metric_failures: list[dict[str, Any]] = []
        self._clock = time.monotonic()
        self._rng_recorded: dict[str, Any] = {}
        self._base_step = 0
        self.restored_from: int | None = None
        self.oracles: dict[str, dict[str, str]] = {}
        """Diagnostic tools a fork added, by name, with the answer each returns."""
        self.clock = self.definition.clock
        self.horizon = self.definition.horizon
        self.now: float | None = None if self.clock is None else self.clock.origin
        self.horizon_reached = False
        self._measured_at: float | None = None
        self._scheduled_recorded: dict[str, Any] = {}
        self._snapshot_store = Path(snapshot_store or ".")
        self.snapshots: Snapshotter | None = (
            WorkspaceSnapshots(
                Path(agent_workspace),
                Path(snapshot_store),
                cap_mib=snapshot_mib,
                ignore=snapshot_ignore,
            )
            if agent_workspace is not None and snapshot_store is not None
            else None
        )

    # Episode operations.

    def start(
        self,
        *,
        initial_state: Mapping[str, Mapping[str, Any]] | None = None,
        info: Any = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Reset every App from the Task's state and keep the opening envelope.

        A Job's host calls this itself before the Harness can act, so the
        episode always starts from the Task's state, whatever the Harness does.

        Returns:
            The opening ``reset`` envelope.
        """
        self.opening = self.reset(initial_state=initial_state, info=info, seed=seed)
        return self.opening

    def agent_reset(self) -> dict[str, Any]:
        """The opening observation, as the Agent may see it.

        A reset never starts the episode over once it has begun: before the
        first action it returns the opening again, and after it an error.

        Returns:
            The Agent's view of the opening envelope.
        """
        if self.finished:
            return self.agent_view(self._ended("reset", None))
        if self.opening is None:
            self.start()
        if self.steps == self._base_step and self.opening is not None:
            return self.agent_view(self.opening)
        return self.agent_view(
            self._envelope(
                "reset",
                observation=None,
                rendered="",
                info={"error": "The episode has already started; it cannot be reset."},
            )
        )

    def agent_argument_error(self, action: Any) -> dict[str, Any]:
        """The Agent's view of an action called without a JSON object of arguments.

        Returns:
            An envelope that carries only the error.
        """
        return self.agent_view(
            self._envelope(
                "step",
                action=str(action),
                observation=None,
                rendered="",
                info={"error": "action arguments must be a JSON object"},
            )
        )

    def oracle(
        self, name: str, arguments: Mapping[str, Any], *, seat: str | None = None
    ) -> dict[str, Any]:
        """Answer a diagnostic fork's added tool, and record the call as a Harness tool step.

        The answer is the one value of App State the fork's ``oracle_tool``
        change named, read now.

        Returns:
            What the Agent sees: the answer as the observation, and the step number.
        """
        wanted = self.oracles.get(name)
        app = self.apps.get(wanted["app"]) if wanted is not None else None
        if wanted is None or app is None:
            return self.agent_view(
                {"observation": None, "rendered": "", "info": {"error": f"no tool {name!r}"}}
            )
        value: Any = self._snapshot(app)
        found = True
        for part in wanted["path"].split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
                value = value[int(part)]
            else:
                found = False
                break
        answer = (
            f"There is no {wanted['path']}."
            if not found
            else value
            if isinstance(value, str)
            else json.dumps(value, sort_keys=True)
        )
        recorded = self.tool(name, dict(arguments), output=answer, seat=seat)
        return self.agent_view(
            {
                "observation": {"text": answer},
                "rendered": answer,
                "terminated": False,
                "truncated": False,
                "info": {"step": recorded["step"]},
            }
        )

    def agent_view(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        """What the Agent may see of an envelope: never a reward, view, State, or step info.

        Any secret value the host holds is masked, in case an App echoed one.

        Returns:
            The observation, rendered text, whether the episode ended, and the
            step number and error, if any.
        """
        visible = {key: envelope.get(key) for key in AGENT_FIELDS}
        raw = envelope.get("info")
        info: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
        visible["info"] = {key: info[key] for key in _AGENT_INFO if key in info}
        return cast(dict[str, Any], self._redact(visible))

    def redact_values(self, values: Sequence[str] | Any) -> None:
        """Mask these values, the Apps' secrets and credentials, in what the Agent sees."""
        kept: set[str] = set()
        for item in values:
            text = str(item)
            # A library error may quote a value stripped or escaped, as repr() does.
            kept.update({text, text.strip(), repr(text)[1:-1], repr(text.encode())[2:-1]})
        kept = {item for item in kept if len(item) >= 4}
        self._hidden = tuple(sorted(kept, key=len, reverse=True))

    def report(self) -> dict[str, Any]:
        """Everything the Job reads back after the episode.

        Returns:
            Each App's snapshots and control level, every step as the host
            recorded it with its rewards and info, each step's App State, the
            last observation and view, and every running metric point and
            ``measure`` failure.
        """
        return {
            "apps": self.snapshot(),
            "steps": [dict(item) for item in self._log],
            "states": list(self._states),
            "observation": self._last_observation,
            "view": self._last_view,
            "metrics": list(self._metrics),
            "metric_failures": list(self._metric_failures),
            "workspace": self.snapshots.report() if self.snapshots is not None else None,
            "restored_from": self.restored_from,
            "clock": None
            if self.clock is None
            else {"now": self.now, "horizon_reached": self.horizon_reached},
        }

    def finish(self) -> dict[str, Any]:
        """End the episode and report it; from now on no action, reset, or turn runs.

        A Harness process that outlives its run could otherwise keep acting
        while the Verifiers read the Apps.

        Returns:
            The same report as :meth:`report`.
        """
        self.finished = True
        report = self.report()
        if self.snapshots is not None and self.snapshots.available:
            # What the Harness left behind, for Verifiers that read the workspace.
            final = self.snapshots.snapshot_final()
            bundle = None
            if final is not None:
                with contextlib.suppress(OSError, RuntimeError):
                    bundle = self.snapshots.export(self._snapshot_store / BUNDLE_FILE)
            report["workspace"] = {
                **self.snapshots.report(),
                "final": final,
                "bundle": str(bundle) if bundle is not None else None,
            }
        return report

    def reset(
        self,
        *,
        initial_state: Mapping[str, Mapping[str, Any]] | None = None,
        info: Any = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        """Reset every App and return the opening envelope.

        Returns:
            A ``reset`` envelope.
        """
        state = dict(initial_state or {})
        texts: list[tuple[str, Any, str]] = []
        self.horizon_reached = False
        self._scheduled_recorded = {}
        self._set_now(None if self.clock is None else self.clock.origin)
        self._measured_at = self.now
        for app in self.apps.values():
            app._scheduled = []
        for name, app in self.apps.items():
            app_state = dict(state.get(name) or {})
            if seed is not None and "seed" not in app_state and _accepts_seed(app):
                app_state["seed"] = seed
            app.seed = seed
            app.rng = random.Random(None if seed is None else f"{seed}:{name}")
            app.task_info = info
            opening = app.reset(app_state)
            payload, rendered = observation_payload(opening)
            if payload is not None:
                texts.append((name, payload, rendered))
        self.initial = {name: self._snapshot(app) for name, app in self.apps.items()}
        self.turns = 0
        self.steps = 0
        self.started = True
        self._recorded = {}
        self._states = []
        self._log = []
        self._metrics = []
        self._metric_failures = []
        self._clock = time.monotonic()
        self._rng_recorded = {}
        self._base_step = 0
        self._record_states(0)
        self._snapshot_workspace(0)
        for hook in self.verifiers:
            # A periodic metric's first point is the world as the episode starts.
            if hook.hook == "measure" and hook.every and hook.every.get("sim_time"):
                self._measure_now(hook)
        if len(texts) == 1:
            observation, rendered = texts[0][1], texts[0][2]
        elif texts:
            observation = {name: payload for name, payload, _ in texts}
            rendered = "\n\n".join(f"## {name}\n{text}" for name, _, text in texts if text)
        else:
            observation, rendered = None, ""
        envelope = self._envelope(
            "reset",
            observation=observation,
            rendered=rendered,
            view=self._view(None),
        )
        if self._states:
            # A checkpoint at step 0 hands this back to the Agent: what it saw, never State.
            opening = self.agent_view(envelope)
            self._states[0]["opening"] = {
                "observation": opening.get("observation"),
                "rendered": opening.get("rendered", ""),
            }
        return envelope

    def step(
        self,
        name: str,
        arguments: Mapping[str, Any],
        *,
        seat: str | None = None,
        unknown: bool = False,
    ) -> dict[str, Any]:
        """Run one exposed action and return its envelope.

        An action that rejects its input with ``ValueError`` is feedback for the
        Agent: the envelope carries the error and the episode continues. Any
        other failure is reported to the Agent without its details, which can
        hold a server's log or a secret, and recorded for the Job.

        With seats, ``seat`` is the one acting. An action from a seat that may
        not act now is refused before it runs, and is not a step.

        A call to a tool that doesn't exist is recorded as an ``unknown_action``
        step, never dropped. ``unknown`` says the Harness didn't offer the tool,
        so the call is recorded that way even when an App has an action by that
        name, such as one the Agent's ``tool_overrides`` hid.

        Returns:
            A ``step`` envelope.
        """
        if self.finished:
            return self._ended("step", name)
        if not self.started:
            self.start()
        if self.horizon_reached:
            return {**self._ended("step", name), "terminated": False, "truncated": True}
        refusal = self._refuse(seat)
        if refusal is not None:
            return self._envelope(
                "step", action=name, observation=None, rendered="", info={"error": refusal}
            )
        self._acting = seat
        for item in self.apps.values():
            item.seat = seat
        try:
            route = None if unknown else self.routes.get(name)
            if self.clock is not None and route == ("", WAIT_ACTION):
                return self._wait(arguments)
            envelope = self._run(name, arguments, unknown=unknown)
            envelope = self._paced(route, arguments, envelope)
            self._after_step()
            return envelope
        finally:
            self._acting = None
            for item in self.apps.values():
                item.seat = None

    # Simulated time.

    def _set_now(self, value: float | None) -> None:
        self.now = value
        for app in self.apps.values():
            app._now = value

    def _label(self, value: float | None = None) -> str:
        if self.clock is None:
            return ""
        return self.clock.label(value if value is not None else (self.now or 0.0))

    def _horizon_end(self) -> float | None:
        if self.clock is None or self.horizon is None or self.horizon.sim_time is None:
            return None
        return self.clock.origin + self.horizon.sim_time

    def _after_step(self) -> None:
        """Run step-period ``measure`` hooks and check the horizon after any step."""
        for hook in self.verifiers:
            every = hook.every or {}
            steps = every.get("steps")
            if hook.hook == "measure" and steps and self.steps % int(steps) == 0:
                self._measure_now(hook)
        self._check_horizon()

    def _check_horizon(self) -> None:
        if self.horizon is None or self.horizon_reached:
            return
        end = self._horizon_end()
        if end is not None and self.now is not None and self.now >= end - 1e-9:
            self.horizon_reached = True
        if self.horizon.max_steps is not None and self.steps >= self.horizon.max_steps:
            self.horizon_reached = True

    def _wait(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """The built-in ``wait``: let time pass to ``until`` or the next event.

        The world's events happen first, each its own step; the wait is the step
        after them, and its observation lists them with their times.

        Returns:
            The wait's envelope.
        """
        assert self.clock is not None and self.now is not None
        problem: str | None = None
        unknown = sorted(str(key) for key in arguments if key != "until")
        until = arguments.get("until")
        target: float | None = None
        if unknown:
            problem = f"wait takes only until, not {', '.join(unknown)}"
        elif until is not None:
            try:
                target = float(until)
            except (TypeError, ValueError):
                problem = f"until must be a number of {self.clock.unit}s, not {until!r}"
            else:
                if not math.isfinite(target):
                    problem = f"until must be a finite number of {self.clock.unit}s"
                elif target < self.now:
                    problem = f"It is already {self._label()}; until must not be earlier."
        else:
            target = self._next_event_time()
            if target is None:
                target = self._horizon_end()
            if target is None:
                problem = "Nothing is scheduled to happen. Give until, the time to wait until."
        end = self._horizon_end()
        if target is not None and end is not None:
            target = min(target, end)
        if problem is not None or target is None:
            self.steps += 1
            self.turns += 1
            self._record_states(self.steps, action=WAIT_ACTION, error=problem)
            self._snapshot_workspace(self.steps)
            envelope = self._logged(
                self._envelope(
                    "step",
                    action=WAIT_ACTION,
                    observation=None,
                    rendered="",
                    info={"step": self.steps, "error": problem},
                ),
                arguments,
            )
            self._after_step()
            return envelope
        started = self.now
        events = self._advance_to(target)
        self.steps += 1
        self.turns += 1
        lines = [f"[{self._label(at)}] {text}" for at, text in events if text]
        summary = (
            f"Waited from {self._label(started)} to {self._label()}."
            if lines
            else f"Waited from {self._label(started)} to {self._label()}. Nothing happened."
        )
        rendered = "\n".join([*lines, summary])
        observation = {
            "text": rendered,
            "now": self.now,
            "events": [{"at": at, "text": text} for at, text in events],
        }
        self._record_states(self.steps, action=WAIT_ACTION)
        self._snapshot_workspace(self.steps)
        self._measure(
            self._step_view("", WAIT_ACTION, arguments, observation, None, None, None), ""
        )
        envelope = self._logged(
            self._envelope(
                "step",
                action=WAIT_ACTION,
                observation=observation,
                rendered=rendered,
                info={"step": self.steps, "sim_time": self.now},
                view=self._view(None),
                timed=True,
            ),
            arguments,
        )
        self._after_step()
        return envelope

    def _paced(
        self,
        route: tuple[str, str] | None,
        arguments: Mapping[str, Any],
        envelope: dict[str, Any],
    ) -> dict[str, Any]:
        """With ``agent_paced`` time, let the action's duration pass, and add what happened.

        Returns:
            The action's envelope, with the events that followed it appended.
        """
        if self.clock is None or self.clock.pacing != "agent_paced" or route is None:
            return envelope
        app = self.apps.get(route[0])
        if app is None or self.now is None:
            return envelope
        duration = float(app.action_duration(route[1], dict(arguments)) or 0.0)
        if not math.isfinite(duration) or duration <= 0:
            return envelope
        target = self.now + duration
        end = self._horizon_end()
        events = self._advance_to(target if end is None else min(target, end))
        lines = [f"[{self._label(at)}] {text}" for at, text in events if text]
        if not lines:
            return envelope
        rendered = "\n".join(
            part for part in (str(envelope.get("rendered") or ""), "Meanwhile:", *lines) if part
        )
        return {**envelope, "rendered": rendered}

    def _next_event_time(self) -> float | None:
        times: list[float] = []
        for app in self.apps.values():
            value = app.next_event_time()
            if value is not None:
                times.append(float(value))
        return min(times) if times else None

    def _next_measure_time(self) -> float | None:
        """When the next sim-time ``measure`` period falls, after the last one measured.

        Returns:
            The time, or ``None`` when no hook measures on a sim-time period.
        """
        if self.clock is None or self._measured_at is None:
            return None
        periods = [
            float(hook.every["sim_time"])
            for hook in self.verifiers
            if hook.hook == "measure" and hook.every and hook.every.get("sim_time")
        ]
        if not periods:
            return None
        origin = self.clock.origin
        upcoming = []
        for period in periods:
            index = math.floor((self._measured_at - origin) / period + 1e-9) + 1
            upcoming.append(origin + index * period)
        return min(upcoming)

    def _advance_to(self, target: float) -> list[tuple[float, str]]:
        """Move the clock to ``target``, running every event and period on the way.

        Returns:
            Each event's time and the text the Agent sees.

        Raises:
            RuntimeError: When an App keeps an event it was already given.
        """
        assert self.now is not None
        happened: list[tuple[float, str]] = []
        last: float | None = None
        repeats = 0
        while True:
            upcoming = [
                value
                for value in (self._next_event_time(), self._next_measure_time())
                if value is not None and value <= target
            ]
            if not upcoming:
                break
            moment = max(self.now, min(upcoming))
            repeats = repeats + 1 if moment == last else 0
            last = moment
            if repeats > 100:
                raise RuntimeError(
                    f"An App keeps an event at {moment:g} after advance({moment:g}). "
                    "Take due events with due_events() in advance()."
                )
            self._set_now(moment)
            happened.extend(self._advance_apps(moment))
            measure_at = self._next_measure_time()
            if measure_at is not None and measure_at <= moment + 1e-9:
                self._measured_at = moment
                for hook in self.verifiers:
                    if hook.hook == "measure" and hook.every and hook.every.get("sim_time"):
                        self._measure_now(hook)
        if target > self.now:
            self._set_now(target)
            happened.extend(self._advance_apps(target))
        return happened

    def _advance_apps(self, moment: float) -> list[tuple[float, str]]:
        """Call each App's ``advance``; record each event it reports as a step.

        Returns:
            Each event's time and text.
        """
        happened: list[tuple[float, str]] = []
        for name, app in self.apps.items():
            for item in app.advance(moment) or ():
                payload, rendered = observation_payload(item)
                if payload is None:
                    continue
                self._event(name, payload, rendered)
                happened.append((moment, rendered))
        return happened

    def _event(self, app_name: str, payload: Any, rendered: str) -> None:
        """Record one thing the world did on its own as a step with ``source: environment``."""
        self.steps += 1
        app = self.apps[app_name]
        step = self._step_view(app_name, "event", {}, payload, None, None, self._snapshot(app))
        if step is not None:
            step = dataclasses.replace(step, source="environment", seat=None)
        self._record_states(self.steps, app=app_name, action="event", source="environment")
        self._snapshot_workspace(self.steps)
        self._measure(step, app_name)
        self._log.append(
            self._redact(
                {
                    "protocol": STEP_PROTOCOL,
                    "kind": "event",
                    "app": app_name,
                    "action": "event",
                    "arguments": {},
                    "observation": json.loads(json.dumps(payload, default=str)),
                    "rendered": f"[{self._label()}] {rendered}",
                    "reward": 0.0,
                    "rewards": [],
                    "terminated": False,
                    "truncated": False,
                    "info": {"step": self.steps, "sim_time": self.now},
                    "view": None,
                    "step": self.steps,
                    "turn": self.turns,
                    "at": time.time(),
                    "t": round(time.monotonic() - self._clock, 3),
                    "source": "environment",
                    "sim_time": self.now,
                }
            )
        )
        for hook in self.verifiers:
            every = hook.every or {}
            steps = every.get("steps")
            if hook.hook == "measure" and steps and self.steps % int(steps) == 0:
                self._measure_now(hook)

    def _measure_now(self, hook: RewardHook) -> None:
        """Run one periodic ``measure`` hook on the Apps as they stand now."""
        if not self.verifiers:
            return
        step = Step(
            task=self.task,
            turn=self.turns,
            app="",
            action="",
            arguments={},
            apps={name: AppView(self, item) for name, item in self.apps.items()},
            seats=self.seats,
            source="environment",
            now=self.now,
        )
        self._measure_hook(hook, step, "")

    def _run(
        self, name: str, arguments: Mapping[str, Any], *, unknown: bool = False
    ) -> dict[str, Any]:
        from plural.environments.env import ActionCall

        self.steps += 1
        arguments = dict(arguments)
        route = None if unknown else self.routes.get(name)
        if route is None:
            # A Harness that offered its own tools tells the model which; listing the
            # Apps' actions here could name one the Agent's overrides hid.
            names = ", ".join(self.routes) or "none"
            available = "" if unknown else f"; available actions: {names}"
            self._record_states(self.steps, action=name, error="unknown action")
            self._snapshot_workspace(self.steps)
            return self._logged(
                self._envelope(
                    "step",
                    action=name,
                    observation=None,
                    rendered="",
                    info={
                        "step": self.steps,
                        "error": f"unknown action {name!r}{available}",
                        "unknown_action": True,
                    },
                ),
                arguments,
            )
        app_name, action_name = route
        app = self.apps[app_name]
        watched = bool(self.verifiers) and app.snapshot_on_step
        previous = self._snapshot(app) if watched else None
        self._effects = []
        started = time.monotonic()
        try:
            result = app.call(action_name, arguments)
        except Exception as exc:  # noqa: BLE001 - a failed action is the Agent's feedback
            self.turns += 1
            internal: str | None = None
            if isinstance(exc, ValueError):
                error = str(exc)
            else:
                traceback.print_exc()
                internal = f"{type(exc).__name__}: {exc}"
                error = f"The {app_name} App could not complete {name}."
            step = self._step_view(
                app_name, action_name, arguments, None, error, previous, previous
            )
            reward, signals = self._reward(step)
            self._record_states(self.steps, app=app_name, action=action_name, error=error)
            self._snapshot_workspace(self.steps)
            self._measure(step, app_name)
            failed: dict[str, Any] = {**app.step_info(), "step": self.steps, "error": error}
            if internal is not None:
                failed["internal_error"] = internal
            return self._logged(
                self._envelope(
                    "step",
                    app=app_name,
                    action=name,
                    observation=None,
                    rendered="",
                    reward=reward,
                    rewards=signals,
                    info=failed,
                    view=self._view(app_name),
                ),
                arguments,
            )
        latency_ms = round((time.monotonic() - started) * 1000, 3)
        self.turns += 1
        payload, rendered = observation_payload(result)
        effect: Any = cast(Any, self.environment.on_step)(
            ActionCall(app=app_name, action=action_name, arguments=arguments, name=name),
            result,
            {key: AppHandle(self, value) for key, value in self.apps.items()},
        )
        if effect is not None:
            raise TypeError(
                "Environment.on_step returned a value, but it only applies effects across "
                "Apps now. Move the reward to a Verifier's reward hook on the Task."
            )
        current = self._snapshot(app) if watched else None
        step = self._step_view(app_name, action_name, arguments, payload, None, previous, current)
        reward, signals = self._reward(step)
        self._record_states(self.steps, app=app_name, action=action_name)
        self._snapshot_workspace(self.steps)
        self._measure(step, app_name)
        info: dict[str, Any] = {
            **app.step_info(),
            "step": self.steps,
            "latency_ms": latency_ms,
        }
        if self._effects:
            info["effects"] = list(self._effects)
        return self._logged(
            self._envelope(
                "step",
                app=app_name,
                action=name,
                observation=payload,
                rendered=rendered,
                reward=reward,
                rewards=signals,
                info=info,
                view=self._view(app_name),
            ),
            arguments,
        )

    def tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        output: Any = None,
        error: str | None = None,
        seat: str | None = None,
        background: bool = False,
    ) -> dict[str, Any]:
        """Record one call of the Harness's own tool, such as ``Bash``, as a step.

        The Harness reports it, since the host did not run it, so the step is
        marked ``reported``. It takes the next step number, so actions and
        Harness tools share one timeline, and the workspace is snapshotted
        after it. No ``reward`` or ``measure`` hook runs on it.

        Returns:
            The step number given to the call, or an error.
        """
        if self.finished:
            return {"error": EPISODE_OVER}
        if not self.started:
            self.start()
        self.steps += 1
        self._acting = seat
        try:
            self._record_states(self.steps, action=name)
            self._snapshot_workspace(self.steps)
            text = output if isinstance(output, str) else json.dumps(output, default=str)
            self._log.append(
                self._redact(
                    {
                        "protocol": STEP_PROTOCOL,
                        "kind": "harness_tool",
                        "reported": True,
                        "app": None,
                        "action": str(name)[:200],
                        "arguments": json.loads(json.dumps(dict(arguments or {}), default=str)),
                        "observation": None if output is None else {"text": text[:20_000]},
                        "rendered": "" if output is None else text[:20_000],
                        "reward": 0.0,
                        "rewards": [],
                        "terminated": False,
                        "truncated": False,
                        "info": {
                            "step": self.steps,
                            **({"error": str(error)[:2000]} if error else {}),
                            **({"background": True} if background else {}),
                        },
                        "view": None,
                        "step": self.steps,
                        "turn": self.turns,
                        "at": time.time(),
                        "t": round(time.monotonic() - self._clock, 3),
                        "source": "agent",
                        **({"seat": seat} if seat is not None else {}),
                    }
                )
            )
        finally:
            self._acting = None
        return {"step": self.steps}

    def restore(
        self,
        *,
        states: Mapping[str, Any],
        rng: Mapping[str, Any] | None = None,
        initial: Mapping[str, Any] | None = None,
        step: int,
        turns: int,
        elapsed: float = 0.0,
        observation: Any = None,
        rendered: str = "",
        info: Any = None,
        seed: int | None = None,
        forced: Sequence[Mapping[str, Any]] = (),
        clock: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Put every App back as it stood after step ``step``, without a reset.

        Sets the step and turn counters, each App's random number generator,
        and the clock; calls each App's :meth:`~plural.App.restore` with its
        State; and keeps observation *k* as the opening, which a Harness that
        resets sees. The Agent's workspace is put back by the Job beforehand,
        and snapshotted here as step ``step``.

        A diagnostic fork's ``forced`` actions run next, as the Agent's, and are
        recorded with ``source: "intervention"``; the last one's result is the
        opening instead.

        Returns:
            The opening envelope: observation *k*.

        Raises:
            ValueError: When an App cannot be restored.
        """
        for name, app in self.apps.items():
            restorable, reason = app.restore_status()
            if not restorable:
                raise ValueError(reason or f"App {name!r} cannot be restored")
            app.seed = seed
            app.rng = random.Random(None if seed is None else f"{seed}:{name}")
            app.task_info = info
            app.restore(copy.deepcopy(states.get(name)))
            saved = (rng or {}).get(name)
            if saved is not None:
                app.rng.setstate(_rng_state(saved))
        if self.clock is not None:
            given = dict(clock or {})
            self._set_now(float(given.get("now", self.clock.origin)))
            measured = given.get("measured_at")
            self._measured_at = self.now if measured is None else float(measured)
            raw = given.get("scheduled")
            scheduled = raw if isinstance(raw, Mapping) else {}
            for name, app in self.apps.items():
                app._scheduled = [dict(item) for item in scheduled.get(name) or ()]
            self.horizon_reached = False
            self._scheduled_recorded = {
                name: copy.deepcopy(app._scheduled) for name, app in self.apps.items()
            }
        self.initial = (
            {key: copy.deepcopy(value) for key, value in initial.items()}
            if initial is not None
            else {name: self._snapshot(app) for name, app in self.apps.items()}
        )
        self.steps = step
        self.turns = turns
        self._base_step = step
        self.restored_from = step
        self.started = True
        self._states = []
        self._log = []
        self._metrics = []
        self._metric_failures = []
        self._clock = time.monotonic() - max(0.0, float(elapsed))
        self._recorded = {
            name: self._snapshot(app) for name, app in self.apps.items() if app.snapshot_on_step
        }
        self._rng_recorded = {name: _rng_payload(app.rng) for name, app in self.apps.items()}
        self._snapshot_workspace(step)
        self.opening = self._envelope(
            "reset",
            observation=observation,
            rendered=rendered,
            info={"restored": step},
            view=self._view(None),
        )
        for item in forced:
            arguments = item.get("arguments")
            envelope = self.step(
                str(item.get("action")), dict(arguments) if isinstance(arguments, Mapping) else {}
            )
            if self._log:
                self._log[-1]["source"] = "intervention"
            self.opening = envelope
        self._base_step = self.steps
        return self.opening

    def turn(self) -> tuple[str, ...] | None:
        """The seats that may act now: those every App that answers allows.

        Returns:
            The seats, in the Task's order, or ``None`` when any seat may act.
        """
        allowed: set[str] | None = None
        for app in self.apps.values():
            answer = app.turn()
            if answer is None:
                continue
            named = {answer} if isinstance(answer, str) else {str(item) for item in answer}
            allowed = named if allowed is None else allowed & named
        if allowed is None:
            return None
        return tuple(seat for seat in self.seats if seat in allowed)

    def seat_view(self, seat: str) -> dict[str, Any]:
        """What one seat may know before it acts: whether it may, and its own view.

        Returns:
            ``your_turn``, the seats that may act, whether the episode ended,
            and each App's :meth:`~plural.App.observe` for this seat.

        Raises:
            KeyError: When ``seat`` is not one of the Task's seats.
        """
        if seat not in self.seats:
            raise KeyError(f"no seat {seat!r}; seats: {', '.join(self.seats)}")
        if self.finished:
            return {
                "seat": seat,
                "your_turn": False,
                "waiting_for": [],
                "terminated": True,
                "truncated": False,
                "observation": None,
                "error": EPISODE_OVER,
            }
        if not self.started:
            self.start()
        ended = bool(self.environment.terminated()) or bool(self.environment.truncated())
        allowed = self.turn()
        observed = {
            name: payload
            for name, app in self.apps.items()
            if (payload := observation_payload(app.observe(seat))[0]) is not None
        }
        observation: Any = next(iter(observed.values())) if len(observed) == 1 else observed or None
        return cast(
            dict[str, Any],
            self._redact(
                {
                    "seat": seat,
                    "your_turn": not ended and (allowed is None or seat in allowed),
                    "waiting_for": [] if ended or allowed is None else list(allowed),
                    "terminated": bool(self.environment.terminated()),
                    "truncated": bool(self.environment.truncated()),
                    "observation": observation,
                }
            ),
        )

    def _ended(self, kind: str, action: str | None) -> dict[str, Any]:
        """The envelope for a request after :meth:`finish`: nothing ran and nothing is logged.

        Returns:
            An envelope that carries only the refusal.
        """
        return {
            "protocol": STEP_PROTOCOL,
            "kind": kind,
            "app": None,
            "action": action,
            "observation": None,
            "rendered": "",
            "reward": 0.0,
            "rewards": [],
            "terminated": True,
            "truncated": False,
            "info": {"error": EPISODE_OVER},
            "view": None,
        }

    def _refuse(self, seat: str | None) -> str | None:
        """Why ``seat`` may not act now.

        Returns:
            The refusal the seat's Agent sees, or ``None`` when it may act.
        """
        if not self.seats:
            return None
        if seat not in self.seats:
            return "This action names no seat of the episode."
        if self.environment.terminated() or self.environment.truncated():
            return "The episode has ended."
        allowed = self.turn()
        if allowed is not None and seat not in allowed:
            waiting = ", ".join(allowed) or "nobody yet"
            return f"It is not your turn. Waiting for: {waiting}."
        return None

    def snapshot(self) -> dict[str, Any]:
        """Report every App's control level and its initial and final snapshots.

        Returns:
            One entry per App.
        """
        report: dict[str, Any] = {}
        for name, app in self.apps.items():
            definition = self.definition.app(name)
            report[name] = {
                "control": definition.control,
                "initial": self.initial.get(name),
                "final": self._snapshot(app),
            }
        return report

    def query(self, app_name: str, action: str, arguments: Mapping[str, Any]) -> Any:
        """Run a read-only action for a Verifier.

        Returns:
            The action's JSON observation.

        Raises:
            PermissionError: When the action can change state.
        """
        if app_name not in self.apps:
            raise KeyError(f"no App {app_name!r}; Apps: {', '.join(self.apps)}")
        declaration = next(
            (item for item in self.definition.app(app_name).actions if item.name == action),
            None,
        )
        if declaration is None:
            raise KeyError(f"App {app_name!r} has no action {action!r}")
        if declaration.mutates_state:
            raise PermissionError(
                f"Verifiers may only call read-only actions; {app_name}.{action} can change "
                "state. Mark it @action(read_only=True), or for MCP set readOnlyHint."
            )
        payload, _ = observation_payload(self.apps[app_name].call(action, dict(arguments)))
        return payload

    def close(self) -> None:
        """Close every App, ignoring failures so each one gets the chance."""
        for app in self.apps.values():
            with contextlib.suppress(Exception):
                app.close()

    # Helpers.

    def _step_view(
        self,
        app: str,
        action: str,
        arguments: Mapping[str, Any],
        observation: Any,
        error: str | None,
        previous: Any,
        current: Any,
    ) -> Step | None:
        """The one action, as ``reward`` and ``measure`` hooks see it.

        Returns:
            The Step, or ``None`` when no hook would read it.
        """
        if not self.verifiers:
            return None
        seat = self._acting
        return Step(
            task=self.task,
            turn=self.turns,
            app=app,
            action=action,
            arguments=copy.deepcopy(dict(arguments)),
            observation=copy.deepcopy(observation),
            error=error,
            previous_state=previous,
            current_state=current,
            apps={name: AppView(self, item) for name, item in self.apps.items()},
            seat=seat,
            seats=self.seats,
        )

    def _reward(self, step: Step | None) -> tuple[float, list[dict[str, Any]]]:
        """Call every ``reward`` hook on one action; a failing hook never fails the action.

        Returns:
            The step's total reward and one signal per Verifier that answered.
        """
        if step is None:
            return 0.0, []
        seat = step.seat
        total = 0.0
        signals: list[dict[str, Any]] = []
        for verifier in self.verifiers:
            if verifier.hook != "reward":
                continue
            entry: dict[str, Any] = {
                "name": verifier.name,
                "version": verifier.version,
                "app": step.app,
            }
            if seat is not None:
                entry["seat"] = seat
            try:
                value = verifier.fn(step)
                if value is None:
                    continue
                credited = self._credited(value, seat)
            except Exception as exc:  # noqa: BLE001 - a reward never fails the action
                signals.append({**entry, "value": 0.0, "error": described(exc)})
                continue
            for credited_seat, number in credited:
                signal = dict(entry)
                if credited_seat is not None:
                    signal["seat"] = credited_seat
                signal["value"] = number
                signals.append(signal)
                if credited_seat == seat:
                    total += number
        return total, signals

    def _measure(self, step: Step | None, acting: str) -> None:
        """Call every per-step ``measure`` hook on one step and keep its running metric values.

        A hook that raises or returns something invalid is recorded in
        ``metric_failures`` and never fails the action. Points stay in memory
        and go to the Job in the signed report, never to a file the Harness
        can read. Hooks with ``every`` run on their period instead.
        """
        if step is None:
            return
        if self.now is not None and step.now is None:
            step = dataclasses.replace(step, now=self.now)
        for hook in self.verifiers:
            if hook.hook == "measure" and not hook.every:
                self._measure_hook(hook, step, acting)

    def _measure_hook(self, hook: RewardHook, step: Step, acting: str) -> None:
        elapsed = round(time.monotonic() - self._clock, 3)
        try:
            values, seats = _measured(hook, hook.fn(step), self.seats)
        except Exception as exc:  # noqa: BLE001 - a metric never fails the action
            self._metric_failures.append(
                self._redact({"step": self.steps, "verifier": hook.name, "error": described(exc)})
            )
            return
        if not values and not seats:
            return
        point: dict[str, Any] = {
            "step": self.steps,
            "t": elapsed,
            "verifier": hook.name,
            "values": values,
            "source": step.source,
        }
        if seats:
            point["seats"] = seats
        clock = self._sim_time(acting)
        if clock is not None:
            point["sim_time"] = clock
        if step.seat is not None:
            point["seat"] = step.seat
        self._metrics.append(point)

    def _sim_time(self, acting: str) -> float | str | None:
        """The simulated time: the acting App's clock, else the first App with one.

        Returns:
            A number of simulated seconds (or the App's own unit, such as days), an
            ISO-8601 timestamp, or ``None`` when no App keeps a clock.
        """
        if self.now is not None:
            return self.now
        order = [acting, *(name for name in self.apps if name != acting)]
        order = [name for name in order if name in self.apps]
        for name in order:
            try:
                value = self.apps[name].sim_time()
            except Exception:  # noqa: BLE001 - a broken clock only loses the time axis
                continue
            if isinstance(value, datetime):
                return value.isoformat()
            if isinstance(value, str):
                try:
                    datetime.fromisoformat(value)
                except ValueError:
                    continue
                return value
            if value is not None:
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(number):
                    return number
        return None

    def _credited(self, value: Any, seat: str | None) -> list[tuple[str | None, float]]:
        """The seats a reward credits: the acting one for a number, or each one named.

        Returns:
            Each credited seat, ``None`` alone, with its value.

        Raises:
            ValueError: When a value is not a finite number or names no seat.
        """
        if isinstance(value, Mapping):
            if not self.seats:
                raise ValueError("a reward mapping of seat to value needs seats")
            unknown = sorted(str(key) for key in value if key not in self.seats)
            if unknown:
                raise ValueError(f"reward names no seat of the episode: {', '.join(unknown)}")
            return [(str(key), _finite(item)) for key, item in value.items()]
        return [(seat, _finite(value))]

    def _logged(self, envelope: dict[str, Any], arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Keep one step as the host saw it, for the Job's ledger and the run viewer.

        Returns:
            ``envelope``, unchanged.
        """
        # An App's internal error or a reward hook's exception can quote a secret.
        self._log.append(
            self._redact(
                {
                    **json.loads(json.dumps(envelope, sort_keys=True, default=str)),
                    "kind": "action",
                    "arguments": json.loads(json.dumps(dict(arguments), default=str)),
                    "step": self.steps,
                    "turn": self.turns,
                    "at": time.time(),
                    "source": "agent",
                    **({"seat": self._acting} if self._acting is not None else {}),
                }
            )
        )
        return envelope

    def _redact(self, value: Any) -> Any:
        if not self._hidden:
            return value
        if isinstance(value, str):
            for secret in self._hidden:
                value = value.replace(secret, "***")
            return value
        if isinstance(value, Mapping):
            return {key: self._redact(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact(item) for item in value]
        return value

    def _record_states(
        self,
        step: int,
        *,
        app: str | None = None,
        action: str | None = None,
        error: str | None = None,
        source: str | None = None,
    ) -> None:
        """Append the State of each App that changed to ``states.jsonl``, beside the Apps.

        Step 0 holds every App's State after reset; each later step only the
        Apps whose State it changed. Replaying a Verifier's ``reward`` on a
        stored Trial reads this file. It stays in the Runtime's workspace and
        is collected with the Trial's artifacts, never sent to the Harness.
        """
        if self.workspace is None:
            return
        changed: dict[str, Any] = {}
        generators: dict[str, Any] = {}
        for name, item in self.apps.items():
            current = _rng_payload(item.rng)
            if step == 0 or current != self._rng_recorded.get(name):
                generators[name] = current
                self._rng_recorded[name] = current
            if not item.snapshot_on_step:
                continue
            snapshot = self._snapshot(item)
            if step == 0 or snapshot != self._recorded.get(name):
                changed[name] = snapshot
                self._recorded[name] = snapshot
        line: dict[str, Any] = {
            "step": step,
            "state": changed,
            "source": source or ("environment" if step == 0 else "agent"),
        }
        if generators:
            line["rng"] = generators
        if self.clock is not None:
            # The clock, and each App's scheduled events where they changed, so a
            # checkpoint at this step puts the world's future back too.
            clock: dict[str, Any] = {"now": self.now, "measured_at": self._measured_at}
            scheduled: dict[str, Any] = {}
            for name, item in self.apps.items():
                pending = copy.deepcopy(item._scheduled)
                if step == 0 or pending != self._scheduled_recorded.get(name):
                    scheduled[name] = pending
                    self._scheduled_recorded[name] = pending
            if scheduled:
                clock["scheduled"] = scheduled
            line["clock"] = clock
        if app is not None:
            line.update(app=app, action=action)
        if error is not None:
            line["error"] = error
        self._states.append(line)
        if self.private_state:
            return
        root = self.workspace / ".plural" / "apps"
        root.mkdir(parents=True, exist_ok=True)
        with (root / STATES_FILE).open("w" if step == 0 else "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, sort_keys=True, default=str) + "\n")

    def recorded_states(self) -> list[dict[str, Any]]:
        """Each step's recorded App State, for the Job to store as ``states.jsonl``.

        Returns:
            One entry per step, oldest first.
        """
        return list(self._states)

    def _snapshot_workspace(self, step: int) -> None:
        if self.snapshots is not None:
            self.snapshots.snapshot(step)

    def _snapshot(self, app: App[Any]) -> Any:
        if not app.has_snapshot():
            return None
        return json.loads(json.dumps(app.snapshot(), sort_keys=True, default=str))

    def _view(self, acting: str | None) -> dict[str, Any] | None:
        override = getattr(self.environment, "view", None)
        if callable(override):
            rendered = override()
            if rendered:
                return dict(rendered)
        order = [acting] if acting else []
        order += [name for name in self.apps if name != acting]
        for name in order:
            if name is None:
                continue
            rendered = self.apps[name].view()
            if rendered:
                return dict(rendered)
        return None

    def _envelope(
        self,
        kind: str,
        *,
        observation: Any,
        rendered: str,
        app: str | None = None,
        action: str | None = None,
        reward: float = 0.0,
        rewards: list[dict[str, Any]] | None = None,
        info: dict[str, Any] | None = None,
        view: dict[str, Any] | None = None,
        timed: bool = False,
    ) -> dict[str, Any]:
        if (
            self.clock is not None
            and kind in {"reset", "step"}
            and self.now is not None
            and not timed
        ):
            # The Agent always knows what time it is; the observation itself is unchanged.
            rendered = f"[{self._label()}] {rendered}".rstrip()
        self._check_horizon()
        envelope = {
            "protocol": STEP_PROTOCOL,
            "kind": kind,
            "app": app,
            "action": action,
            "observation": observation,
            "rendered": rendered,
            "reward": reward,
            "rewards": rewards or [],
            "terminated": bool(self.environment.terminated()),
            "truncated": bool(self.environment.truncated()) or self.horizon_reached,
            "info": info or {},
            "view": view,
        }
        self._persist(envelope)
        return envelope

    def _persist(self, envelope: Mapping[str, Any]) -> None:
        """Keep the last observation and view for the run viewer, and outside a Job write them."""
        observation = envelope.get("observation")
        if observation is not None:
            payload = observation if isinstance(observation, Mapping) else {"value": observation}
            self._last_observation = json.loads(json.dumps(payload, default=str))
        if envelope.get("view"):
            self._last_view = json.loads(json.dumps(envelope["view"], default=str))
        if self.workspace is None or self.private_state:
            return
        root = self.workspace / ".plural" / "apps"
        root.mkdir(parents=True, exist_ok=True)
        if envelope.get("observation") is not None:
            (root / "observation.json").write_text(
                json.dumps(
                    {"observation": envelope["observation"], "rendered": envelope["rendered"]},
                    sort_keys=True,
                    default=str,
                )
                + "\n",
                encoding="utf-8",
            )
        if envelope.get("view"):
            (root / "view.json").write_text(
                json.dumps(envelope["view"], sort_keys=True, default=str) + "\n",
                encoding="utf-8",
            )
        for name, app in self.apps.items():
            if not app.snapshot_on_step:
                continue
            directory = root / name
            directory.mkdir(parents=True, exist_ok=True)
            snapshot = self._snapshot(app)
            if snapshot is not None:
                (directory / "state.json").write_text(
                    json.dumps(snapshot, sort_keys=True) + "\n", encoding="utf-8"
                )


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"reward must be a finite number, not {number!r}")
    return number


def _measured(
    hook: RewardHook, value: Any, seats: Sequence[str] = ()
) -> tuple[dict[str, float | None], dict[str, dict[str, float | None]]]:
    """Check what a ``measure`` hook returned: its declared running metrics, as numbers.

    A metric's value may be one number, or with seats a mapping of seat to
    number, which gives each seat its own series.

    Returns:
        Each metric's value, ``None`` where it does not apply, and each seat's
        values for the metrics measured per seat.

    Raises:
        ValueError: When it is not a mapping, names an undeclared metric or an
            unknown seat, or a value is not a finite number.
    """
    if value is None:
        return {}, {}
    if not isinstance(value, Mapping):
        raise ValueError(
            f"measure must return a mapping of running metric to value, not {type(value).__name__}"
        )
    unknown = sorted(str(key) for key in value if key not in hook.metrics)
    if unknown:
        raise ValueError(
            f"measure returned {', '.join(unknown)}, which the Verifier does not declare as "
            f"running metrics ({', '.join(hook.metrics) or 'none'})"
        )
    measured: dict[str, float | None] = {}
    by_seat: dict[str, dict[str, float | None]] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            if not seats:
                raise ValueError(f"{key}: a mapping of seat to value needs seats")
            strangers = sorted(str(seat) for seat in item if seat not in seats)
            if strangers:
                raise ValueError(f"{key} names no seat of the episode: {', '.join(strangers)}")
            for seat, number in item.items():
                by_seat.setdefault(str(seat), {})[str(key)] = (
                    None if number is None else _finite(number)
                )
            continue
        measured[str(key)] = None if item is None else _finite(item)
    return measured, by_seat


def _rng_payload(generator: random.Random) -> list[Any]:
    """A generator's state as JSON: ``[version, internal state, gauss_next]``.

    Returns:
        The JSON-safe state.
    """
    version, internal, gauss = generator.getstate()
    return [version, list(internal), gauss]


def _rng_state(payload: Any) -> tuple[Any, ...]:
    """The state :func:`_rng_payload` wrote, ready for ``random.Random.setstate``.

    Returns:
        The state tuple.
    """
    version, internal, gauss = payload
    return (int(version), tuple(int(item) for item in internal), gauss)


def _accepts_seed(app: App[Any]) -> bool:
    return "seed" in app._state_type().model_fields


__all__ = [
    "AGENT_FIELDS",
    "STATES_FILE",
    "STEPS_FILE",
    "STEP_PROTOCOL",
    "AppHandle",
    "AppHost",
    "AppView",
    "RewardHook",
    "load_reward_hooks",
]
