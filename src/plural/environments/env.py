"""The Environment: Apps composed with one Runtime, policy, and set of limits."""

from __future__ import annotations

import importlib.util
import inspect
import sys
import sysconfig
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from plural.apps.base import App
from plural.common import PackageSource
from plural.environments.action_registry import action
from plural.environments.definition import (
    EnvironmentDefinition,
    EnvironmentResource,
    EnvironmentRuntime,
    ExecutionLimits,
    Guardrail,
    HarnessPolicy,
    Party,
)

if TYPE_CHECKING:
    from plural.apps.host import AppHost


@dataclass(frozen=True)
class ActionCall:
    """One action the Agent took: which App, which action, and its arguments."""

    app: str
    action: str
    arguments: dict[str, Any] = field(default_factory=dict)
    name: str = ""


def _caller_root() -> Path | None:
    """The folder of the first user file on the call stack, outside Plural.

    Returns:
        That folder, or ``None`` when every frame is library code.
    """
    frame = sys._getframe(1)
    package = Path(__file__).resolve().parents[1]
    stdlib = Path(sysconfig.get_paths()["stdlib"]).resolve()
    while frame is not None:
        filename = frame.f_code.co_filename
        if not filename.startswith("<"):
            path = Path(filename).resolve()
            installed = {"site-packages", "dist-packages"} & set(path.parts)
            if not (installed or path.is_relative_to(package) or path.is_relative_to(stdlib)):
                return path.parent
        frame = frame.f_back  # type: ignore[assignment]
    return None


class Environment:
    """Apps the Agent acts in, with one Runtime, policy, and set of limits.

    An Environment owns the episode: ``reset`` and ``step``, the table of
    actions every App offers, and the rule that the Agent only ever sees an
    action's observation. Most Environments need no subclass::

        environment = Environment(apps=[Wordle()], runtime=Runtime.docker())

    Subclass it only when Apps affect one another. Override :meth:`on_step`
    to react after any App's action, or :meth:`terminated` to end the episode
    from the state of several Apps.
    """

    name = "environment"
    version = "0.1.0"
    description = ""
    overview = ""
    readme = ""
    _source_file: ClassVar[Path | None] = None
    metadata: dict[str, Any] = {}
    party: Party | int | Mapping[str, int] | None = None

    def __init__(
        self,
        *,
        apps: Iterable[App[Any]] = (),
        runtime: EnvironmentRuntime | Mapping[str, Any] | None = None,
        name: str | None = None,
        version: str | None = None,
        description: str | None = None,
        overview: str | None = None,
        readme: str | None = None,
        resources: Iterable[EnvironmentResource] = (),
        guardrails: Iterable[Guardrail] = (),
        harness_policy: HarnessPolicy | None = None,
        limits: ExecutionLimits | None = None,
        party: Party | int | Mapping[str, int] | None = None,
        metadata: dict[str, Any] | None = None,
        source: str | Path | None = None,
    ) -> None:
        self.apps: tuple[App[Any], ...] = tuple(apps)
        for item in self.apps:
            if not isinstance(item, App):
                raise TypeError(
                    f"apps must contain App instances, got {type(item).__name__}. "
                    "Subclass plural.App, or use App.mcp(...) to connect a server."
                )
        default_name = self.apps[0].name if len(self.apps) == 1 else type(self).name
        self.name = name or (type(self).name if type(self).name != "environment" else default_name)
        self.version = version or type(self).version
        self.description = type(self).description if description is None else description
        self.overview = type(self).overview if overview is None else overview
        self.readme = type(self).readme if readme is None else readme
        if runtime is None:
            raise ValueError(
                f"Cannot create Environment {self.name!r}.\n"
                "runtime is required and says where the Agent and Apps execute.\n"
                "Pass a Runtime preset:\n"
                "  Environment(apps=[...], runtime=Runtime.docker())\n"
                "  Environment(apps=[...], runtime=Runtime.local())\n"
                "  Environment(apps=[...], runtime=Runtime.daytona())"
            )
        if isinstance(runtime, Mapping):
            runtime = EnvironmentRuntime.model_validate(runtime)
        self.runtime = runtime
        self.resources = tuple(resources)
        self.guardrails = tuple(guardrails)
        self.harness_policy = harness_policy or HarnessPolicy()
        self.limits = limits or ExecutionLimits()
        chosen = type(self).party if party is None else party
        self.party = None if chosen is None else Party.model_validate(chosen)
        self.metadata = deepcopy(type(self).metadata) if metadata is None else deepcopy(metadata)
        self._source: PackageSource | None = None
        self._source_bound = False
        self._root: Path | None = None
        self._compiled: EnvironmentDefinition | None = None
        self._host: AppHost | None = None
        self._bind_source(source)

    # Cross-App hooks.

    def on_step(self, call: ActionCall, result: Any, apps: Mapping[str, Any]) -> None:
        """React after any App's action, for effects that span Apps.

        ``apps`` maps each App's name to a handle with ``call(action, **args)``,
        ``snapshot()``, and ``state``. An effect here is not an Agent action and
        is not shown to the Agent. Apps never call each other directly.

        Rewards are not given here: they depend on the Task, so they come from
        the ``reward`` hook of a Task's Verifier.
        """
        del call, result, apps

    def terminated(self) -> bool:
        """Return whether the episode is over. Default: any App says it is."""
        return any(item.terminated() for item in self.apps)

    def truncated(self) -> bool:
        """Return whether the episode was cut short. Default: any App says so."""
        return any(item.truncated() for item in self.apps)

    # Source and identity.

    @property
    def source(self) -> PackageSource | None:
        """The folder a Job uploads to run this Environment's Apps, with its digest."""
        if not self._source_bound:
            from plural.harness.retrieval import source_digest

            self._source_bound = True
            if self._root is not None:
                self._source = PackageSource(
                    kind="local",
                    uri=str(self._root),
                    digest=source_digest(self._root),
                    trusted=True,
                )
        return self._source

    @source.setter
    def source(self, value: PackageSource | None) -> None:
        self._source = value
        self._source_bound = True

    def _bind_source(self, source: str | Path | None) -> None:
        if source is not None:
            requested = Path(source).expanduser().resolve()
            root: Path | None = requested.parent if requested.is_file() else requested
        elif type(self) is not Environment and type(self).__module__ != "__main__":
            defined = type(self).__dict__.get("_source_file")
            root = defined.parent if defined else _caller_root()
        else:
            root = _caller_root()
        self._root = root if root is not None and root.is_dir() else None
        if self._root is not None:
            for app in self.apps:
                app.workspace = self._root
        self._source = None
        self._source_bound = False
        self._compiled = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        module = sys.modules.get(cls.__module__)
        filename = getattr(module, "__file__", None) if module is not None else None
        cls._source_file = Path(filename).resolve() if filename else None

    def _python_reference(self) -> str | None:
        if type(self) is Environment:
            return None
        filename = type(self).__dict__.get("_source_file")
        if not filename or self._root is None:
            raise ValueError(
                f"Environment subclass {type(self).__name__} must be defined in a .py file "
                "inside its source folder so a Job can run its hooks"
            )
        relative = filename.relative_to(self._root).as_posix()
        return f"{relative}:{type(self).__qualname__}"

    @property
    def content_hash(self) -> str:
        """Stable hash of the compiled Environment configuration and source."""
        return self.definition().content_hash

    @property
    def identity(self) -> Any:
        """Exact Environment identity used by planning."""
        return self.definition().identity

    def definition(self) -> EnvironmentDefinition:
        """Compile exactly one canonical Environment revision.

        Returns:
            The immutable definition used by Jobs and hosted publication.
        """
        if self._compiled is not None:
            return self._compiled
        compiled = EnvironmentDefinition(
            name=self.name,
            version=self.version,
            description=self.description,
            overview=self.overview,
            readme=self.readme,
            apps=tuple(item.definition(self._root) for item in self.apps),
            python=self._python_reference(),
            guardrails=self.guardrails,
            resources=self.resources,
            runtime=self.runtime,
            harness_policy=self.harness_policy,
            limits=self.limits,
            party=None if self.party is None else Party.model_validate(self.party),
            metadata=deepcopy(self.metadata),
            source=self.source,
        )
        self._compiled = compiled
        return compiled

    @classmethod
    def _from_definition(
        cls, definition: EnvironmentDefinition, root: str | Path | None = None
    ) -> Environment:
        """Rebuild an Environment and its Apps from a compiled definition.

        ``root`` is the folder holding the Environment's source files, where
        each Python App class and the optional Environment subclass live.

        Returns:
            The rebuilt Environment, ready to reset.
        """
        base = Path(root).resolve() if root is not None else None
        if base is None and definition.source is not None and definition.source.kind == "local":
            base = Path(definition.source.uri).expanduser().resolve()
        apps = [_rebuild_app(item, base) for item in definition.apps]
        environment_cls: type[Environment] = Environment
        if definition.python:
            loaded = load_reference(definition.python, base)
            if not (isinstance(loaded, type) and issubclass(loaded, Environment)):
                raise ValueError(f"{definition.python} is not an Environment subclass")
            environment_cls = loaded
        environment = environment_cls.__new__(environment_cls)
        Environment.__init__(
            environment,
            apps=apps,
            runtime=definition.runtime,
            name=definition.name,
            version=definition.version,
            description=definition.description,
            overview=definition.overview,
            readme=definition.readme,
            resources=definition.resources,
            guardrails=definition.guardrails,
            harness_policy=definition.harness_policy,
            limits=definition.limits,
            party=definition.party,
            metadata=definition.metadata,
            source=base,
        )
        environment.source = definition.source
        environment._compiled = definition
        return environment

    # In-process episode API, for local development and tests.

    def reset(
        self,
        *,
        initial_state: Mapping[str, Any] | None = None,
        info: Any = None,
        seed: int | None = None,
        verifiers: Sequence[Any] = (),
    ) -> tuple[Any, dict[str, Any]]:
        """Start an episode in this process.

        ``initial_state`` maps each App's name to its starting state; with one
        App it may be that App's state directly. ``verifiers`` gives each
        :meth:`step` its reward: Verifiers with a ``reward`` hook, or functions
        of one :class:`~plural.Step`.

        Returns:
            The opening observation and reset information.
        """
        from plural.apps.host import AppHost, RewardHook
        from plural.verifiers import DeterministicVerifier, StepTask

        hooks: list[RewardHook] = []
        for item in verifiers:
            if isinstance(item, DeterministicVerifier):
                if item.reward_fn is not None:
                    hooks.append(RewardHook(item.name, item.version, item.reward_fn))
            elif callable(item):
                hooks.append(RewardHook(getattr(item, "__name__", "step"), "", item))
            else:
                raise TypeError(
                    "verifiers takes Verifiers with a reward hook, or functions of one Step; "
                    f"got {type(item).__name__}."
                )
        if self._host is not None:
            self._host.close()
        self._host = AppHost(self, verifiers=hooks, task=StepTask(info=info))
        envelope = self._host.reset(
            initial_state=normalize_initial_state(self.definition(), initial_state or {}),
            info=info,
            seed=seed,
        )
        return envelope["observation"], envelope["info"]

    def step(
        self, action: str | Mapping[str, Any] | None = None, /, **kwargs: Any
    ) -> tuple[Any, float, bool, bool, dict[str, Any]]:
        """Apply one Agent action in this process.

        ``action`` is an exposed action name with keyword arguments, or a
        mapping with ``name`` and the arguments. With exactly one action the
        name may be omitted.

        Returns:
            Observation, reward, terminated, truncated, and step information.
        """
        if self._host is None:
            self.reset()
        assert self._host is not None
        if isinstance(action, Mapping):
            payload = {**action, **kwargs}
            name = payload.pop("name", None) or payload.pop("action", None)
        else:
            name, payload = action, dict(kwargs)
        if not name:
            exposed = self.definition().actions
            if len(exposed) != 1:
                raise ValueError("step requires an action name")
            name = exposed[0].name
        envelope = self._host.step(str(name), payload)
        info = dict(envelope["info"])
        if envelope.get("rewards"):
            info["rewards"] = envelope["rewards"]
        return (
            envelope["observation"],
            float(envelope["reward"]),
            bool(envelope["terminated"]),
            bool(envelope["truncated"]),
            info,
        )

    def snapshot(self) -> dict[str, Any]:
        """Return each App's state, as a Verifier receives it after the episode."""
        if self._host is None:
            return {}
        return self._host.snapshot()

    def close(self) -> None:
        """End the in-process episode and release every App's connections."""
        if self._host is not None:
            self._host.close()
            self._host = None


def normalize_initial_state(
    definition: EnvironmentDefinition, state: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Key a Task's initial state by App name.

    With one App, a Task may give that App's state directly, such as
    ``{"secret": "crane"}``. It is stored as ``{"wordle": {"secret": "crane"}}``.

    Returns:
        The initial state for each App.

    Raises:
        ValueError: When a key names no App, or a value is not an object.
    """
    if not state:
        return {}
    names = [item.name for item in definition.apps]
    if len(names) == 1 and set(state) != {names[0]}:
        return {names[0]: dict(state)}
    unknown = sorted(set(state) - set(names))
    if unknown:
        available = ", ".join(names) or "none"
        raise ValueError(
            f"initial_state names {unknown[0]!r}, which is not an App of Environment "
            f"{definition.name!r}. Key initial_state by App name; Apps: {available}."
        )
    keyed: dict[str, dict[str, Any]] = {}
    for key, value in state.items():
        if not isinstance(value, Mapping):
            raise ValueError(f"initial_state.{key} must be an object of that App's state")
        keyed[str(key)] = dict(value)
    return keyed


def load_reference(reference: str, root: Path | None) -> Any:
    """Import ``file.py:Object`` from an Environment source folder.

    Returns:
        The named object.
    """
    script, separator, qualname = reference.partition(":")
    if not separator or not script or not qualname:
        raise ValueError(f"reference must be file.py:Object, got {reference!r}")
    path = Path(script)
    if not path.is_absolute():
        path = (root or Path.cwd()) / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"file not found for {reference!r}: {path}")
    module_name = f"_plural_source_{abs(hash(str(path)))}"
    module = sys.modules.get(module_name)
    if module is None:
        if str(path.parent) not in sys.path:
            sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ValueError(f"could not load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    target: Any = module
    for part in qualname.split("."):
        target = getattr(target, part)
    return target


def _rebuild_app(definition: Any, root: Path | None) -> App[Any]:
    from plural.apps.registry import app_class

    cls: type[App[Any]]
    if definition.python:
        loaded = load_reference(definition.python, root)
        if not (isinstance(loaded, type) and issubclass(loaded, App)):
            raise ValueError(f"{definition.python} is not an App subclass")
        cls = loaded
    else:
        cls = app_class(definition.kind)
    parameters = inspect.signature(cls.__init__).parameters
    accepts_name = "name" in parameters or any(
        item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()
    )
    config = dict(definition.config)
    if "actions" in inspect.signature(cls.__init__).parameters and "actions" not in config:
        config["actions"] = [item.model_dump(mode="json") for item in definition.actions]
    if accepts_name:
        return cls(name=definition.name, **config)
    app = cls(**config)
    app.name = definition.name
    return app


__all__ = [
    "ActionCall",
    "Environment",
    "action",
    "load_reference",
    "normalize_initial_state",
]
