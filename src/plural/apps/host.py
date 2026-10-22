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
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from plural.apps.base import App, observation_payload
from plural.common import described
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
    """A Task Verifier's ``reward`` hook, loaded where the Apps run."""

    name: str
    version: str
    fn: Callable[[Step], Any]


def load_reward_hooks(root: Path, entries: Sequence[Mapping[str, Any]]) -> list[RewardHook]:
    """Import each Verifier's ``reward`` hook from the files the Job staged under ``root``.

    Each entry names a Verifier, its version, its hook as ``file.py:function``,
    and the folder holding its source, relative to ``root``.

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
        loaded.append(RewardHook(name=name, version=str(entry.get("version") or ""), fn=function))
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
        if self.steps == 0 and self.opening is not None:
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
            recorded it with its rewards and info, each step's App State, and
            the last observation and view.
        """
        return {
            "apps": self.snapshot(),
            "steps": [dict(item) for item in self._log],
            "states": list(self._states),
            "observation": self._last_observation,
            "view": self._last_view,
        }

    def finish(self) -> dict[str, Any]:
        """End the episode and report it; from now on no action, reset, or turn runs.

        A Harness process that outlives its run could otherwise keep acting
        while the Verifiers read the Apps.

        Returns:
            The same report as :meth:`report`.
        """
        self.finished = True
        return self.report()

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
        self._record_states(0)
        if len(texts) == 1:
            observation, rendered = texts[0][1], texts[0][2]
        elif texts:
            observation = {name: payload for name, payload, _ in texts}
            rendered = "\n\n".join(f"## {name}\n{text}" for name, _, text in texts if text)
        else:
            observation, rendered = None, ""
        return self._envelope(
            "reset",
            observation=observation,
            rendered=rendered,
            view=self._view(None),
        )

    def step(
        self, name: str, arguments: Mapping[str, Any], *, seat: str | None = None
    ) -> dict[str, Any]:
        """Run one exposed action and return its envelope.

        An action that rejects its input with ``ValueError`` is feedback for the
        Agent: the envelope carries the error and the episode continues. Any
        other failure is reported to the Agent without its details, which can
        hold a server's log or a secret, and recorded for the Job.

        With seats, ``seat`` is the one acting. An action from a seat that may
        not act now is refused before it runs, and is not a step.

        Returns:
            A ``step`` envelope.
        """
        if self.finished:
            return self._ended("step", name)
        if not self.started:
            self.start()
        refusal = self._refuse(seat)
        if refusal is not None:
            return self._envelope(
                "step", action=name, observation=None, rendered="", info={"error": refusal}
            )
        self._acting = seat
        for item in self.apps.values():
            item.seat = seat
        try:
            return self._run(name, arguments)
        finally:
            self._acting = None
            for item in self.apps.values():
                item.seat = None

    def _run(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        from plural.environments.env import ActionCall

        self.steps += 1
        arguments = dict(arguments)
        route = self.routes.get(name)
        if route is None:
            available = ", ".join(self.routes) or "none"
            return self._logged(
                self._envelope(
                    "step",
                    action=name,
                    observation=None,
                    rendered="",
                    info={
                        "step": self.steps,
                        "error": f"unknown action {name!r}; available actions: {available}",
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
            reward, signals = self._reward(
                app_name, action_name, arguments, None, error, previous, previous
            )
            self._record_states(self.steps, app=app_name, action=action_name, error=error)
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
        reward, signals = self._reward(
            app_name, action_name, arguments, payload, None, previous, current
        )
        self._record_states(self.steps, app=app_name, action=action_name)
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

    def _reward(
        self,
        app: str,
        action: str,
        arguments: Mapping[str, Any],
        observation: Any,
        error: str | None,
        previous: Any,
        current: Any,
    ) -> tuple[float, list[dict[str, Any]]]:
        """Call every ``reward`` hook on one action; a failing hook never fails the action.

        Returns:
            The step's total reward and one signal per Verifier that answered.
        """
        if not self.verifiers:
            return 0.0, []
        seat = self._acting
        step = Step(
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
        total = 0.0
        signals: list[dict[str, Any]] = []
        for verifier in self.verifiers:
            entry: dict[str, Any] = {
                "name": verifier.name,
                "version": verifier.version,
                "app": app,
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
                    "arguments": json.loads(json.dumps(dict(arguments), default=str)),
                    "step": self.steps,
                    "turn": self.turns,
                    "at": time.time(),
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
        for name, item in self.apps.items():
            if not item.snapshot_on_step:
                continue
            snapshot = self._snapshot(item)
            if step == 0 or snapshot != self._recorded.get(name):
                changed[name] = snapshot
                self._recorded[name] = snapshot
        line: dict[str, Any] = {"step": step, "state": changed}
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
    ) -> dict[str, Any]:
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
            "truncated": bool(self.environment.truncated()),
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
