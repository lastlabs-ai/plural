"""Run one episode across an Environment's Apps.

The App host owns everything that happens behind the action boundary: it
resets every App from the Task's initial state, routes each exposed action to
its App, runs the Environment's ``on_step`` hook, calls each of the Task's
Rewarders' ``step`` hooks, and reports snapshots for their ``final`` hooks. It
returns one step envelope per call.

The Agent sees only an envelope's ``observation`` (as ``rendered`` text).
Rewards, snapshots, and views are bookkeeping and never reach the Agent.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from plural.apps.base import App, observation_payload
from plural.rewarders import Step, StepTask

if TYPE_CHECKING:
    from plural.environments.env import Environment

STEP_PROTOCOL = "plural-step-v1"


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
    """What a Rewarder's ``step`` hook may read of one App: never an action that writes."""

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
        return self._host._snapshot(self._app)

    def query(self, action: str, /, **arguments: Any) -> Any:
        """Call one of the App's read-only actions.

        Returns:
            The action's observation.
        """
        return self._host.query(self._app.name, action, arguments)


@dataclass(frozen=True)
class StepRewarder:
    """A Task Rewarder's ``step`` hook, loaded where the Apps run."""

    name: str
    version: str
    fn: Callable[[Step], Any]


def load_step_rewarders(root: Path, entries: Sequence[Mapping[str, Any]]) -> list[StepRewarder]:
    """Import each Rewarder's ``step`` hook from the files the Job staged under ``root``.

    Each entry names a Rewarder, its version, its hook as ``file.py:function``,
    and the folder holding its source, relative to ``root``.

    Returns:
        The hooks, in the Task's order.

    Raises:
        ValueError: When a hook's file or function is missing.
    """
    loaded: list[StepRewarder] = []
    for entry in entries:
        name = str(entry["name"])
        folder = (root / str(entry["dir"])).resolve()
        file_name, _, function_name = str(entry["python"]).rpartition(":")
        path = folder / file_name
        if not path.is_file():
            raise ValueError(f"Rewarder {name!r}: its step hook file {file_name} is missing")
        module_name = f"_plural_rewarder_{uuid.uuid4().hex}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Rewarder {name!r}: cannot import {file_name}")
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
                raise ValueError(f"Rewarder {name!r}: {file_name} has no {function_name}")
        loaded.append(StepRewarder(name=name, version=str(entry.get("version") or ""), fn=function))
    return loaded


class AppHost:
    """Episode state for one Environment's Apps in one process."""

    def __init__(
        self,
        environment: Environment,
        workspace: str | Path | None = None,
        *,
        rewarders: Sequence[StepRewarder] = (),
        task: StepTask | None = None,
    ) -> None:
        self.environment = environment
        self.definition = environment.definition()
        self.apps: dict[str, App[Any]] = {item.name: item for item in environment.apps}
        self.routes = {item.name: (item.app, item.action) for item in self.definition.actions}
        self.workspace = Path(workspace) if workspace is not None else None
        if self.workspace is not None:
            for app in self.apps.values():
                app.workspace = self.workspace
        self.rewarders = tuple(rewarders)
        self.task = task or StepTask()
        self.initial: dict[str, Any] = {}
        self.turns = 0
        self.started = False
        self._effects: list[dict[str, Any]] = []

    # Episode operations.

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
            app.task_info = info
            opening = app.reset(app_state)
            payload, rendered = observation_payload(opening)
            if payload is not None:
                texts.append((name, payload, rendered))
        self.initial = {name: self._snapshot(app) for name, app in self.apps.items()}
        self.turns = 0
        self.started = True
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

    def step(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Run one exposed action and return its envelope.

        An action that rejects its input with ``ValueError`` is feedback for the
        Agent: the envelope carries the error and the episode continues.

        Returns:
            A ``step`` envelope.
        """
        from plural.environments.env import ActionCall

        if not self.started:
            self.reset()
        route = self.routes.get(name)
        if route is None:
            available = ", ".join(self.routes) or "none"
            return self._envelope(
                "step",
                action=name,
                observation=None,
                rendered="",
                info={"error": f"unknown action {name!r}; available actions: {available}"},
            )
        app_name, action_name = route
        app = self.apps[app_name]
        arguments = dict(arguments)
        watched = bool(self.rewarders) and app.snapshot_on_step
        previous = self._snapshot(app) if watched else None
        self._effects = []
        started = time.monotonic()
        try:
            result = app.call(action_name, arguments)
        except ValueError as exc:
            self.turns += 1
            reward, signals = self._reward(
                app_name, action_name, arguments, None, str(exc), previous, previous
            )
            return self._envelope(
                "step",
                app=app_name,
                action=name,
                observation=None,
                rendered="",
                reward=reward,
                rewards=signals,
                info={**app.step_info(), "error": str(exc)},
                view=self._view(app_name),
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
                "Apps now. Move the reward to a Rewarder's step hook on the Task."
            )
        current = self._snapshot(app) if watched else None
        reward, signals = self._reward(
            app_name, action_name, arguments, payload, None, previous, current
        )
        info: dict[str, Any] = {**app.step_info(), "latency_ms": latency_ms}
        if self._effects:
            info["effects"] = list(self._effects)
        return self._envelope(
            "step",
            app=app_name,
            action=name,
            observation=payload,
            rendered=rendered,
            reward=reward,
            rewards=signals,
            info=info,
            view=self._view(app_name),
        )

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
        """Run a read-only action for a Rewarder.

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
                f"Rewarders may only call read-only actions; {app_name}.{action} can change "
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
        """Call every ``step`` hook on one action; a failing hook never fails the action.

        Returns:
            The step's total reward and one signal per Rewarder that answered.
        """
        if not self.rewarders:
            return 0.0, []
        step = Step(
            task=self.task,
            turn=self.turns,
            app=app,
            action=action,
            arguments=dict(arguments),
            observation=observation,
            error=error,
            previous_state=previous,
            current_state=current,
            apps={name: AppView(self, item) for name, item in self.apps.items()},
        )
        total = 0.0
        signals: list[dict[str, Any]] = []
        for rewarder in self.rewarders:
            entry: dict[str, Any] = {
                "name": rewarder.name,
                "version": rewarder.version,
                "app": app,
            }
            try:
                value = rewarder.fn(step)
                if value is None:
                    continue
                entry["value"] = float(value)
            except Exception as exc:  # noqa: BLE001 - a reward never fails the action
                entry.update({"value": 0.0, "error": f"{type(exc).__name__}: {exc}"})
            else:
                total += entry["value"]
            signals.append(entry)
        return total, signals

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
        """Write the last observation and view, and cheap snapshots, for the run viewer."""
        if self.workspace is None:
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


def _accepts_seed(app: App[Any]) -> bool:
    return "seed" in app._state_type().model_fields


__all__ = [
    "STEP_PROTOCOL",
    "AppHandle",
    "AppHost",
    "AppView",
    "StepRewarder",
    "load_step_rewarders",
]
