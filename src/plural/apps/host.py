"""Run one episode across an Environment's Apps.

The App host owns everything that happens behind the action boundary: it
resets every App from the Task's initial state, routes each exposed action to
its App, scores the App's rewarders, runs the Environment's ``on_step`` hook,
and reports snapshots for Verifiers. It returns one step envelope per call.

The Agent sees only an envelope's ``observation`` (as ``rendered`` text).
Rewards, snapshots, and views are bookkeeping and never reach the Agent.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from plural.apps.base import App, observation_payload

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
        """The App's current snapshot, or ``None``."""
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


class AppHost:
    """Episode state for one Environment's Apps in one process."""

    def __init__(self, environment: Environment, workspace: str | Path | None = None) -> None:
        self.environment = environment
        self.definition = environment.definition()
        self.apps: dict[str, App[Any]] = {item.name: item for item in environment.apps}
        self.routes = {item.name: (item.app, item.action) for item in self.definition.actions}
        self.workspace = Path(workspace) if workspace is not None else None
        if self.workspace is not None:
            for app in self.apps.values():
                app.workspace = self.workspace
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
            app.task_info = info  # type: ignore[attr-defined]
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
        self._persist()
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
        previous = self._snapshot(app) if app.snapshot_on_step else None
        self._effects = []
        started = time.monotonic()
        try:
            result = app.call(action_name, arguments)
        except ValueError as exc:
            self.turns += 1
            return self._envelope(
                "step",
                app=app_name,
                action=name,
                observation=None,
                rendered="",
                info={"error": str(exc)},
                view=self._view(app_name),
            )
        latency_ms = round((time.monotonic() - started) * 1000, 3)
        self.turns += 1
        current = self._snapshot(app) if app.snapshot_on_step else None
        payload, rendered = observation_payload(result)
        reward, signals = _score(
            app,
            previous,
            current,
            {"name": action_name, **arguments},
            payload,
        )
        extra = self.environment.on_step(
            ActionCall(app=app_name, action=action_name, arguments=arguments, name=name),
            result,
            {key: AppHandle(self, value) for key, value in self.apps.items()},
        )
        if extra is not None:
            value = float(extra)
            signals.append({"name": "on_step", "app": None, "weight": 1.0, "value": value})
            reward += value
        info: dict[str, Any] = {"latency_ms": latency_ms}
        if self._effects:
            info["effects"] = list(self._effects)
        self._persist()
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
            try:
                app.close()
            except Exception:  # noqa: BLE001, S110 - closing must reach every App
                pass

    # Helpers.

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
        return {
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

    def _persist(self) -> None:
        if self.workspace is None:
            return
        root = self.workspace / ".plural" / "apps"
        for name, app in self.apps.items():
            directory = root / name
            directory.mkdir(parents=True, exist_ok=True)
            snapshot = self._snapshot(app)
            if snapshot is not None:
                (directory / "state.json").write_text(
                    json.dumps(snapshot, sort_keys=True) + "\n", encoding="utf-8"
                )


def _accepts_seed(app: App[Any]) -> bool:
    return "seed" in app._state_type().model_fields


def _score(
    app: App[Any],
    previous: Any,
    current: Any,
    action: dict[str, Any],
    result: Any,
) -> tuple[float, list[dict[str, Any]]]:
    signals: list[dict[str, Any]] = []
    total = 0.0
    for config, method in app._rewarder_methods():
        weight = float(config["weight"])
        entry: dict[str, Any] = {"name": str(config["name"]), "app": app.name, "weight": weight}
        try:
            value = float(method(previous, current, action, result))
        except Exception as exc:  # noqa: BLE001
            # A reward signal must never fail the action that already ran.
            entry.update({"value": 0.0, "error": str(exc)})
        else:
            entry["value"] = value
            total += weight * value
        signals.append(entry)
    return total, signals


__all__ = ["STEP_PROTOCOL", "AppHandle", "AppHost"]
