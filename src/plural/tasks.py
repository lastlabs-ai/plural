"""First-class schema-v2 Task and Benchmark definitions."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from plural.common import FrozenModel, content_hash, semantic_version, stable_id
from plural.environments.definition import EnvironmentDefinition, EnvironmentResource
from plural.environments.env import Environment
from plural.verifiers import DeterministicVerifier, VerifierDefinition, WeightedVerifier

if TYPE_CHECKING:
    from plural.client import Client


def _json_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _schema_types(spec: Mapping[str, Any]) -> set[str]:
    raw = spec.get("type")
    if isinstance(raw, str):
        names = {raw}
    elif isinstance(raw, list):
        names = {str(item) for item in raw}
    else:
        names = set()
    if "integer" in names:
        names.add("number")
    return names


def validate_task_state(
    *,
    task_id: str,
    environment_name: str,
    state: Any,
    state_schema: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate Task-injected Environment state against the pinned schema.

    Returns:
        The accepted state mapping, or an empty mapping when ``state`` is omitted.

    Raises:
        ValueError: When ``state`` has unknown keys, wrong types, or is missing
            a required field that has no default.
    """
    if state is None:
        return {}
    if not isinstance(state, dict):
        raise ValueError(
            f"Cannot create Task {task_id!r} on Environment {environment_name!r}.\n"
            f"initial_state must be an object, got {_json_type_name(state)}."
        )
    properties = state_schema.get("properties")
    fields = properties if isinstance(properties, dict) else {}
    settable = {
        key
        for key, spec in fields.items()
        if isinstance(spec, dict) and spec.get("x-plural-initial") is True
    }
    unknown = [key for key in state if not isinstance(fields.get(key), dict)]
    errors: list[str] = []
    if unknown:
        errors.append(
            "initial_state has fields the Environment State does not define: "
            + ", ".join(repr(key) for key in unknown)
            + "."
        )
    for key, value in state.items():
        spec = fields.get(key)
        if not isinstance(spec, dict):
            continue
        if settable and key not in settable:
            errors.append(
                f"initial_state cannot set {key!r}. "
                "Only State fields marked with initial() can be supplied by a Task."
            )
            continue
        expected = _schema_types(spec)
        actual = _json_type_name(value)
        if expected and actual not in expected and not (value is None and "null" in expected):
            errors.append(
                f"initial_state {key!r} expected {' or '.join(sorted(expected))}, got {actual}."
            )
            continue
        errors.extend(_constraint_errors(key, value, spec))
    required = state_schema.get("required")
    if isinstance(required, list):
        for key in required:
            spec = fields.get(key)
            if key in state or not isinstance(spec, dict) or "default" in spec:
                continue
            if settable and key not in settable:
                continue
            errors.append(f"initial_state is missing required State field {key!r}.")
    if errors:
        available = ", ".join(sorted(fields)) if fields else "(none)"
        raise ValueError(
            f"Cannot create Task {task_id!r} on Environment {environment_name!r}.\n"
            + "\n".join(errors)
            + f"\n{environment_name} State fields: {available}"
        )
    return {str(key): value for key, value in state.items()}


def _constraint_errors(key: str, value: Any, spec: Mapping[str, Any]) -> list[str]:
    """Return failures of the limits declared on one initial State field."""
    phrase = _constraint_phrase(spec)
    errors: list[str] = []
    if isinstance(value, str):
        minimum = spec.get("minLength")
        maximum = spec.get("maxLength")
        pattern = spec.get("pattern")
        too_short = isinstance(minimum, int) and len(value) < minimum
        too_long = isinstance(maximum, int) and len(value) > maximum
        mismatched = isinstance(pattern, str) and re.fullmatch(pattern, value) is None
        if phrase and (too_short or too_long or mismatched):
            errors.append(f"initial_state {key!r} must be {phrase}.")
        else:
            if too_short:
                errors.append(f"initial_state {key!r} must be at least {minimum} characters.")
            if too_long:
                errors.append(f"initial_state {key!r} must be at most {maximum} characters.")
            if mismatched:
                errors.append(f"initial_state {key!r} must match {pattern!r}.")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = spec.get("minimum")
        maximum = spec.get("maximum")
        if isinstance(minimum, (int, float)) and value < minimum:
            errors.append(f"initial_state {key!r} must be at least {minimum}.")
        if isinstance(maximum, (int, float)) and value > maximum:
            errors.append(f"initial_state {key!r} must be at most {maximum}.")
        exclusive_minimum = spec.get("exclusiveMinimum")
        exclusive_maximum = spec.get("exclusiveMaximum")
        if isinstance(exclusive_minimum, (int, float)) and value <= exclusive_minimum:
            errors.append(f"initial_state {key!r} must be greater than {exclusive_minimum}.")
        if isinstance(exclusive_maximum, (int, float)) and value >= exclusive_maximum:
            errors.append(f"initial_state {key!r} must be less than {exclusive_maximum}.")
    if isinstance(value, list):
        minimum = spec.get("minItems")
        maximum = spec.get("maxItems")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"initial_state {key!r} must have at least {minimum} items.")
        if isinstance(maximum, int) and len(value) > maximum:
            errors.append(f"initial_state {key!r} must have at most {maximum} items.")
    choices = spec.get("enum")
    if isinstance(choices, list) and value not in choices:
        rendered = ", ".join(repr(item) for item in choices)
        errors.append(f"initial_state {key!r} must be one of {rendered}.")
    return errors


def _constraint_phrase(spec: Mapping[str, Any]) -> str | None:
    """Return a short requirement for a fixed number of letters, when the pattern says so.

    Returns:
        A phrase such as ``exactly 5 lowercase letters``, or ``None``.
    """
    pattern = spec.get("pattern")
    if not isinstance(pattern, str):
        return None
    lowercase = re.fullmatch(r"\^\[a-z\]\{(\d+)\}\$", pattern)
    if lowercase:
        return f"exactly {lowercase.group(1)} lowercase letters"
    letters = re.fullmatch(r"\^\[A-Za-z\]\{(\d+)\}\$", pattern)
    if letters:
        return f"exactly {letters.group(1)} letters"
    return None


def _task_bind_errors(task: Task) -> list[str]:
    errors: list[str] = []
    environment = task.environment
    env_name = getattr(environment, "name", None) or "unknown"
    header = f"Cannot create Task {task.name!r} on Environment {env_name!r}."
    if not isinstance(environment, (Environment, EnvironmentDefinition, Mapping)):
        errors.append(
            f"Cannot create Task {task.name!r}.\n"
            "environment must be an Environment instance.\n"
            f"Got {type(environment).__name__}."
        )
        return errors
    definition = (
        environment.definition()
        if isinstance(environment, Environment)
        else environment
        if isinstance(environment, EnvironmentDefinition)
        else None
    )
    if (
        isinstance(environment, Environment)
        and environment._actions()
        and environment.source is None
    ):
        errors.append(
            f"Cannot create Task {task.name!r}.\n"
            f"Environment {environment.name!r} has @action methods but no source "
            "tree, so a Job cannot execute them.\n"
            "Define the Environment class in a .py file next to the files it needs."
        )
    if not task.verifiers:
        errors.append(
            f"{header}\nA Task needs at least one Verifier that scores the completed Episode."
        )
    for verifier in task.verifiers:
        if isinstance(verifier, DeterministicVerifier):
            check = verifier.check
            if not (
                callable(check)
                or (isinstance(check, dict) and check.get("python"))
                or (isinstance(check, tuple) and check)
            ):
                errors.append(
                    f"{header}\n"
                    f"Verifier {verifier.name!r} check must be a function that accepts an Episode\n"
                    "(observation, state, trajectory, artifacts, usage).\n"
                    f"Got: {type(check).__name__}. Define it like:\n"
                    "  def solved(episode: Episode) -> VerifierOutput: ...\n"
                    "  DeterministicVerifier(name='solved', check=solved)"
                )
    if definition is not None:
        try:
            validate_task_state(
                task_id=task.name,
                environment_name=definition.name,
                state=task.initial_state,
                state_schema=definition.state_schema,
            )
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def _hosted_slug(value: Any, kind: str) -> str:
    """Return the hosted slug or id for a bound Environment or Verifier."""
    from plural.studio import slugify

    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        raw = value.get("slug") or value.get("name")
    else:
        raw = getattr(value, "slug", None) or getattr(value, "name", None)
    if isinstance(raw, str) and raw:
        return slugify(raw)
    raise ValueError(f"Task {kind} {value!r} does not name a hosted slug or id")


class Task(FrozenModel):
    """One versioned unit of work in a Python-authored Environment."""

    name: str = Field(min_length=1)
    version: str = "0.1.0"
    instructions: str = Field(min_length=1)
    goals: tuple[str, ...] = ()
    info: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    environment: Any
    verifiers: tuple[VerifierDefinition, ...] = Field(min_length=1)
    resources: tuple[EnvironmentResource, ...] = ()
    initial_state: dict[str, Any] = Field(default_factory=dict)
    reset_options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _compile_environment(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if "name" not in payload and "task_id" in payload:
            payload["name"] = payload.pop("task_id")
        if "version" not in payload and "revision" in payload:
            payload["version"] = payload.pop("revision")
        if "initial_state" not in payload and "state" in payload:
            payload["initial_state"] = payload.pop("state")
        return payload

    @model_validator(mode="after")
    def _validate_task(self) -> Task:
        semantic_version(self.version)
        errors = _task_bind_errors(self)
        if errors:
            raise ValueError("\n".join(errors))
        return self

    def _environment_definition(self) -> EnvironmentDefinition:
        environment = self.environment
        if isinstance(environment, EnvironmentDefinition):
            return environment
        if isinstance(environment, Environment):
            return environment.definition()
        if isinstance(environment, Mapping):
            return EnvironmentDefinition.model_validate(environment)
        raise ValueError(
            f"Cannot create Task {self.name!r}.\n"
            "environment must be an Environment instance.\n"
            f"Got {type(environment).__name__}."
        )

    @property
    def task_id(self) -> str:
        """Compatibility identity used by the execution engine."""
        return self.name

    @property
    def revision(self) -> str:
        """Compatibility version name used by hosted internals."""
        return self.version

    @property
    def state(self) -> dict[str, Any]:
        """Compatibility initial-state name used by the execution engine."""
        return self.initial_state

    @property
    def public_payload(self) -> dict[str, Any]:
        """Task fields visible to an Agent."""
        return {
            "name": self.name,
            "instructions": self.instructions,
            "goals": self.goals,
            "info": self.info,
            "metadata": self.metadata,
        }

    @property
    def content_hash(self) -> str:
        """Stable Task version digest."""
        environment = self._environment_definition()
        return content_hash(
            {
                "name": self.name,
                "version": self.version,
                "instructions": self.instructions,
                "goals": self.goals,
                "info": self.info,
                "metadata": self.metadata,
                "environment": environment.content_hash,
                "verifiers": [verifier.content_hash for verifier in self.verifiers],
                "resources": self.resources,
                "initial_state": self.initial_state,
                "reset_options": self.reset_options,
            }
        )

    @property
    def identity(self) -> str:
        """Stable Task identifier."""
        return stable_id("tsk", self)

    def definition(self) -> TaskDefinition:
        """Compile this Task into the current execution contract.

        This is the same local-object to hosted-revision bridge that
        ``Environment.definition()`` provides: ``client.create()``,
        ``client.update()``, and ``client.push()`` all accept the compiled
        definition, so a public ``Task`` works with the hosted APIs exactly
        like a public ``Environment`` does.

        Returns:
            The immutable execution definition used by Jobs and hosted publication.
        """
        return TaskDefinition(
            task_id=self.name,
            revision=self.version,
            source_hash=self.content_hash,
            instructions=self.instructions,
            goals=self.goals,
            environment=self._environment_definition(),
            verifiers=tuple(
                WeightedVerifier(verifier=verifier, weight=verifier.weight)
                for verifier in self.verifiers
            ),
            info=self.info,
            metadata=self.metadata,
            resources=self.resources,
            state=self.initial_state,
            reset_options=self.reset_options,
        )

    def _definition(self) -> TaskDefinition:
        """Compile this Task into the current execution contract.

        Returns:
            The internal immutable execution definition.
        """
        return self.definition()

    def push(
        self,
        client: Client | None = None,
        *,
        environment_revision_id: str | None = None,
        verifier_revision_ids: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Publish this Task as a hosted revision, creating its parent by slug.

        This mirrors ``client.tasks.push()``, so the revision-id contract is
        unchanged: pass explicit ids to pin exact dependencies, or omit them
        to resolve each bound Environment and Verifier to its current
        published revision in the same project, exactly like
        ``plural task push`` does for ``task.yaml`` slugs.

        Args:
            client: Configured hosted client. Defaults to ambient configuration
                (``PLURAL_API_KEY`` and friends) when omitted.
            environment_revision_id: Exact hosted Environment revision to pin.
            verifier_revision_ids: Exact hosted Verifier revisions, aligned
                with this Task's verifiers.

        Returns:
            The hosted task revision record.
        """
        from plural.client import Client
        from plural.studio import resolve_published_revision

        active = client if client is not None else Client()
        if environment_revision_id is None:
            environment_revision_id, _ = resolve_published_revision(
                active.environments,
                "environment",
                _hosted_slug(self.environment, "environment"),
            )
        if verifier_revision_ids is None:
            verifier_revision_ids = [
                resolve_published_revision(
                    active.verifiers, "verifier", _hosted_slug(verifier, "verifier")
                )[0]
                for verifier in self.verifiers
            ]
        return active.tasks.push(
            self.definition(),
            environment_revision_id=environment_revision_id,
            verifier_revision_ids=list(verifier_revision_ids),
        )

    def delete(self, client: Client | None = None) -> None:
        """Delete this Task's hosted parent and all of its revisions.

        Args:
            client: Configured hosted client. Defaults to ambient configuration
                when omitted.
        """
        from plural.client import Client
        from plural.studio import slugify

        active = client if client is not None else Client()
        active.tasks.delete(slugify(self.name))


class TaskDefinition(FrozenModel):
    """First-class Task revision pinned to one Environment and Verifiers."""

    schema_version: Literal["2"] = "2"
    task_id: str = Field(min_length=1)
    revision: str = Field(default="0.1.0", min_length=1)
    source_hash: str | None = None
    instructions: str = Field(min_length=1)
    goals: tuple[str, ...] = ()
    environment: EnvironmentDefinition
    verifiers: tuple[WeightedVerifier, ...] = Field(min_length=1)
    info: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    resources: tuple[EnvironmentResource, ...] = ()
    state: dict[str, Any] = Field(default_factory=dict)
    reset_options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _state_fits_environment(self) -> TaskDefinition:
        validate_task_state(
            task_id=self.task_id,
            environment_name=self.environment.name,
            state=self.state,
            state_schema=self.environment.state_schema,
        )
        return self

    @property
    def public_payload(self) -> dict[str, Any]:
        """Task fields visible to an Agent."""
        return {
            "task_id": self.task_id,
            "instructions": self.instructions,
            "goals": self.goals,
            "info": self.info,
            "metadata": self.metadata,
        }

    @property
    def content_hash(self) -> str:
        """Stable Task revision digest."""
        return self.source_hash or content_hash(self.model_dump(exclude={"source_hash"}))

    @property
    def identity(self) -> str:
        """Stable Task revision identifier."""
        return stable_id("tsk", self)


class BenchmarkDefinition(FrozenModel):
    """A revisioned ordered selection of Tasks across Environments."""

    schema_version: Literal["2"] = "2"
    name: str = Field(min_length=1)
    revision: str = Field(default="0.1.0", min_length=1)
    source_hash: str | None = None
    tasks: tuple[TaskDefinition, ...] = Field(min_length=1)
    primary_metric: str = "score"
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_tasks(self) -> BenchmarkDefinition:
        identities = [task.identity for task in self.tasks]
        if len(identities) != len(set(identities)):
            raise ValueError("benchmark Task revisions must be unique")
        return self

    @property
    def content_hash(self) -> str:
        """Stable Benchmark revision digest."""
        return self.source_hash or content_hash(self.model_dump(exclude={"source_hash"}))

    @property
    def benchmark_id(self) -> str:
        """Stable Benchmark revision identifier."""
        return stable_id("bmk", self)


class TaskPin(FrozenModel):
    """Immutable Task identity pinned by a Benchmark."""

    name: str
    version: str
    content_hash: str


class TaskUpdate(FrozenModel):
    """One Task name whose pinned version or content changed."""

    before: TaskPin
    after: TaskPin


class BenchmarkDiff(FrozenModel):
    """Canonical structured difference between two Benchmark versions."""

    added: tuple[TaskPin, ...] = ()
    removed: tuple[TaskPin, ...] = ()
    updated: tuple[TaskUpdate, ...] = ()
    reordered: bool = False
    configuration_changes: dict[str, tuple[Any, Any]] = Field(default_factory=dict)

    @property
    def changed(self) -> bool:
        """Whether any pinned dependency or Benchmark setting changed."""
        return bool(
            self.added
            or self.removed
            or self.updated
            or self.reordered
            or self.configuration_changes
        )


class Benchmark(FrozenModel):
    """A semantic version that pins an ordered set of Tasks."""

    name: str = Field(min_length=1)
    version: str
    tasks: tuple[Task, ...] = Field(min_length=1)
    primary_metric: str = "score"
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _valid_benchmark(self) -> Benchmark:
        semantic_version(self.version)
        names = [task.name for task in self.tasks]
        if len(names) != len(set(names)):
            raise ValueError("benchmark Task names must be unique")
        return self

    @property
    def task_pins(self) -> tuple[TaskPin, ...]:
        """Ordered immutable Task identities."""
        return tuple(
            TaskPin(name=task.name, version=task.version, content_hash=task.content_hash)
            for task in self.tasks
        )

    @property
    def content_hash(self) -> str:
        """Stable Benchmark version digest."""
        return content_hash(
            {
                "name": self.name,
                "version": self.version,
                "task_pins": self.task_pins,
                "primary_metric": self.primary_metric,
                "description": self.description,
                "metadata": self.metadata,
            }
        )

    @property
    def benchmark_id(self) -> str:
        """Stable Benchmark identifier."""
        return stable_id("bmk", self)

    def diff(self, other: Benchmark) -> BenchmarkDiff:
        """Return the structured pin and configuration changes from this version."""
        before = {pin.name: pin for pin in self.task_pins}
        after = {pin.name: pin for pin in other.task_pins}
        added = tuple(after[name] for name in after.keys() - before.keys())
        removed = tuple(before[name] for name in before.keys() - after.keys())
        updated = tuple(
            TaskUpdate(before=before[name], after=after[name])
            for name in before.keys() & after.keys()
            if before[name] != after[name]
        )
        shared_before = [pin.name for pin in self.task_pins if pin.name in after]
        shared_after = [pin.name for pin in other.task_pins if pin.name in before]
        configuration_changes = {
            field: (getattr(self, field), getattr(other, field))
            for field in ("primary_metric", "description", "metadata")
            if getattr(self, field) != getattr(other, field)
        }
        return BenchmarkDiff(
            added=tuple(sorted(added, key=lambda pin: pin.name)),
            removed=tuple(sorted(removed, key=lambda pin: pin.name)),
            updated=tuple(sorted(updated, key=lambda item: item.before.name)),
            reordered=shared_before != shared_after,
            configuration_changes=configuration_changes,
        )

    def dependency_graph(self) -> dict[str, Any]:
        """Export the complete pinned graph in deterministic dependency order.

        Returns:
            Benchmark metadata and all pinned Task dependencies.
        """
        environments: dict[str, dict[str, Any]] = {}
        verifiers: dict[str, dict[str, Any]] = {}
        task_payloads: list[dict[str, Any]] = []
        for task in self.tasks:
            environment = task._environment_definition()
            environments.setdefault(
                environment.content_hash,
                environment.model_dump(mode="json"),
            )
            for verifier in task.verifiers:
                verifiers.setdefault(
                    verifier.content_hash,
                    verifier.model_dump(mode="json"),
                )
            task_payloads.append(task._definition().model_dump(mode="json"))
        return {
            "benchmark": {
                "name": self.name,
                "version": self.version,
                "primary_metric": self.primary_metric,
                "description": self.description,
                "metadata": self.metadata,
                "task_pins": [pin.model_dump(mode="json") for pin in self.task_pins],
                "content_hash": self.content_hash,
            },
            "tasks": task_payloads,
            "environments": [environments[digest] for digest in sorted(environments)],
            "verifiers": [verifiers[digest] for digest in sorted(verifiers)],
        }

    def export(self) -> dict[str, Any]:
        """Return the deterministic complete dependency graph."""
        return self.dependency_graph()

    def _definition(self) -> BenchmarkDefinition:
        """Compile this Benchmark into the current execution contract.

        Returns:
            The internal immutable execution definition.
        """
        return BenchmarkDefinition(
            name=self.name,
            revision=self.version,
            source_hash=self.content_hash,
            tasks=tuple(task._definition() for task in self.tasks),
            primary_metric=self.primary_metric,
            description=self.description,
            metadata=self.metadata,
        )


__all__ = [
    "Benchmark",
    "BenchmarkDefinition",
    "BenchmarkDiff",
    "Task",
    "TaskDefinition",
    "TaskPin",
    "TaskUpdate",
    "validate_task_state",
]
