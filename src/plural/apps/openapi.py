"""Connect an HTTP API described by an OpenAPI document as an App.

Each operation becomes an action named by its ``operationId``. Its path,
query, and header parameters and its JSON body's fields become the action's
arguments. ``GET``, ``HEAD``, and ``OPTIONS`` operations are read-only, so
Verifiers may query them; every other method changes state.

An error response (status 400 or above) is feedback: the Agent sees the
status and body, and the episode continues.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import yaml

from plural.apps.base import App
from plural.apps.definition import AppAction, SecretReference
from plural.apps.hooks import argv, run_hook, snapshot_output
from plural.apps.mcp import expand, referenced_variables
from plural.environments.types import State

_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
_READ_ONLY = frozenset({"get", "head", "options"})
_LOCATIONS = ("path", "query", "header")


def load_document(spec: str, workspace: Path, *, timeout: float = 30) -> dict[str, Any]:
    """Read an OpenAPI document from a file in the workspace or a URL.

    Returns:
        The parsed document.

    Raises:
        ValueError: When it cannot be read or parsed.
    """
    if spec.startswith(("http://", "https://")):
        try:
            response = httpx.get(spec, timeout=timeout, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError(f"Could not fetch the OpenAPI document {spec}: {exc}") from exc
        text = response.text
    else:
        path = Path(spec) if Path(spec).is_absolute() else workspace / spec
        if not path.is_file():
            raise ValueError(f"OpenAPI document {path} does not exist")
        text = path.read_text(encoding="utf-8")
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        document = yaml.safe_load(text)
    if not isinstance(document, dict) or not isinstance(document.get("paths"), dict):
        raise ValueError(f"{spec} is not an OpenAPI document: it has no paths")
    return document


def _resolve(value: Any, document: Mapping[str, Any], depth: int = 0) -> Any:
    """Inline local ``$ref`` pointers, stopping at a fixed depth for cycles.

    Returns:
        ``value`` with its references replaced.
    """
    if depth > 12:
        return {}
    if isinstance(value, Mapping):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/"):
            target: Any = document
            for part in reference[2:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                target = target.get(part, {}) if isinstance(target, Mapping) else {}
            return _resolve(target, document, depth + 1)
        return {key: _resolve(item, document, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item, document, depth + 1) for item in value]
    return value


def _action_name(operation: Mapping[str, Any], method: str, path: str) -> str:
    raw = str(operation.get("operationId") or f"{method}_{path}")
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")[:64]
    return name or method


def operation_actions(
    document: Mapping[str, Any], *, timeout_seconds: float = 30
) -> tuple[AppAction, ...]:
    """Turn every operation in an OpenAPI document into an action.

    Returns:
        One action per operation, with its HTTP route in ``binding``.
    """
    actions: list[AppAction] = []
    seen: set[str] = set()
    for path, item in (document.get("paths") or {}).items():
        if not isinstance(item, Mapping):
            continue
        shared = [_resolve(entry, document) for entry in item.get("parameters") or ()]
        for method in _METHODS:
            operation = item.get(method)
            if not isinstance(operation, Mapping):
                continue
            name = _action_name(operation, method, str(path))
            if name in seen:
                continue
            seen.add(name)
            properties: dict[str, Any] = {}
            required: list[str] = []
            located: dict[str, list[str]] = {location: [] for location in _LOCATIONS}
            own = [_resolve(entry, document) for entry in operation.get("parameters") or ()]
            by_key = {(entry.get("in"), entry.get("name")): entry for entry in [*shared, *own]}
            for (location, parameter), entry in by_key.items():
                if location not in _LOCATIONS or not isinstance(parameter, str):
                    continue
                if location == "header" and parameter.lower() == "authorization":
                    continue
                schema = dict(entry.get("schema") or {"type": "string"})
                if entry.get("description"):
                    schema.setdefault("description", entry["description"])
                properties[parameter] = schema
                located[location].append(parameter)
                if entry.get("required") or location == "path":
                    required.append(parameter)
            body_fields: list[str] | None = None
            body = _resolve(operation.get("requestBody") or {}, document)
            content = body.get("content") if isinstance(body, Mapping) else None
            schema = (content or {}).get("application/json", {}).get("schema")
            if isinstance(schema, Mapping):
                fields = schema.get("properties")
                if (
                    schema.get("type", "object") == "object"
                    and isinstance(fields, Mapping)
                    and not set(fields) & set(properties)
                ):
                    properties.update(fields)
                    body_fields = list(fields)
                    required.extend(str(item) for item in schema.get("required") or ())
                else:
                    properties["body"] = dict(schema)
                    if body.get("required"):
                        required.append("body")
            parameters: dict[str, Any] = {"type": "object", "properties": properties}
            if required:
                parameters["required"] = sorted(set(required))
            summary = operation.get("summary") or operation.get("description") or name
            actions.append(
                AppAction(
                    name=name,
                    description=str(summary).strip(),
                    parameters=parameters,
                    mutates_state=method not in _READ_ONLY,
                    timeout_seconds=timeout_seconds,
                    binding={
                        "method": method.upper(),
                        "path": str(path),
                        **{f"{location}_params": names for location, names in located.items()},
                        "body_fields": body_fields,
                    },
                )
            )
    return tuple(actions)


class OpenAPIApp(App[State]):
    """An App backed by an HTTP API and its OpenAPI document.

    Settings:
        spec: The OpenAPI document: a file in the Environment folder, or a URL.
        base_url: Where to send requests. Default: the document's first server.
        headers: HTTP headers; values may reference ``${SECRET}``.
        operations: Only offer these operationIds. Default: every operation.
        exclude: Never offer these operationIds.
        reset: Command run at the start of each episode, from the workspace,
            with the App's initial state as JSON on stdin.
        snapshot: Command that prints the App's state as JSON, for Verifiers.
        local: Set when the API runs inside the Runtime, so a fresh Runtime is
            a fresh API.
        actions: Operation declarations to use instead of reading ``spec``.
        secrets: Setup secrets the project supplies, for hooks and Verifiers.
        credentials: Names the running Agent supplies, such as its own API token.
        timeout_seconds: How long one request may take.
    """

    kind = "openapi"
    snapshot_on_step = False

    def __init__(
        self,
        *,
        name: str | None = None,
        spec: str | None = None,
        base_url: str | None = None,
        headers: Mapping[str, str] | None = None,
        operations: Sequence[str] | None = None,
        exclude: Sequence[str] = (),
        reset: str | Sequence[str] | None = None,
        snapshot: str | Sequence[str] | None = None,
        local: bool = False,
        actions: Sequence[Mapping[str, Any] | AppAction] | None = None,
        secrets: Iterable[str | SecretReference] | None = None,
        credentials: Iterable[str | SecretReference] | None = None,
        description: str | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        super().__init__(
            name=name or type(self).name or None,
            description=description,
            secrets=secrets,
            credentials=credentials,
        )
        if spec is None and actions is None:
            raise ValueError(f"OpenAPI App {self.name!r} needs spec: a file or URL")
        self.spec = spec
        self.base_url = base_url
        self.headers = dict(headers or {})
        self.operation_filter = tuple(operations) if operations is not None else None
        self.exclude = tuple(exclude)
        self.reset_command = argv(reset)
        self.snapshot_command = argv(snapshot)
        self.local = local
        self.timeout_seconds = timeout_seconds
        self._pinned = (
            tuple(
                item if isinstance(item, AppAction) else AppAction.model_validate(item)
                for item in actions
            )
            if actions is not None
            else None
        )
        self._document: dict[str, Any] | None = None
        self._client: httpx.Client | None = None
        undeclared = sorted(
            referenced_variables(self.headers.values())
            - {
                SecretReference.model_validate(item).name
                for item in (*self.secrets, *self.credentials)
            }
        )
        if undeclared:
            raise ValueError(
                f"OpenAPI App {self.name!r} headers reference {', '.join(undeclared)}; "
                "list them in credentials when the running Agent supplies them, or in "
                "secrets when the project does"
            )

    def document(self) -> dict[str, Any]:
        """The OpenAPI document, read once.

        Returns:
            The parsed document.

        Raises:
            ValueError: When the App was built from pinned actions without a spec.
        """
        if self._document is None:
            if self.spec is None:
                raise ValueError(f"OpenAPI App {self.name!r} has no spec to read")
            self._document = load_document(self.spec, self.workspace, timeout=self.timeout_seconds)
        return self._document

    def actions(self) -> tuple[AppAction, ...]:
        """The API's operations, filtered by ``operations`` and ``exclude``.

        Returns:
            One action per offered operation.

        Raises:
            ValueError: When ``operations`` names one the document lacks.
        """
        offered = self._pinned
        if offered is None:
            offered = operation_actions(self.document(), timeout_seconds=self.timeout_seconds)
        by_name = {item.name: item for item in offered}
        if self.operation_filter is not None:
            missing = [item for item in self.operation_filter if item not in by_name]
            if missing and self._pinned is None:
                available = ", ".join(sorted(by_name)) or "none"
                raise ValueError(
                    f"OpenAPI App {self.name!r} lists operations the document does not "
                    f"have: {', '.join(missing)}. It has: {available}"
                )
            offered = tuple(by_name[item] for item in self.operation_filter if item in by_name)
        return tuple(item for item in offered if item.name not in self.exclude)

    def _base(self) -> str:
        if self.base_url:
            return self.base_url
        servers = self.document().get("servers") if self.spec is not None else None
        url = servers[0].get("url") if isinstance(servers, list) and servers else None
        if not isinstance(url, str) or not url:
            raise ValueError(
                f"OpenAPI App {self.name!r} needs base_url: its document lists no servers"
            )
        if self.spec and self.spec.startswith(("http://", "https://")):
            return urljoin(self.spec, url)
        return url

    def call(self, action: str, arguments: Mapping[str, Any]) -> Any:
        """Send the request behind one action.

        Returns:
            The response body: a JSON object as is, a JSON list as ``items``,
            or the text.

        Raises:
            ValueError: For an unknown action, missing arguments, or an error
                response; the Agent sees the message.
        """
        declared = {item.name: item for item in self.actions()}
        spec = declared.get(action)
        if spec is None:
            raise ValueError(
                f"unknown action {action!r}; available actions: {', '.join(sorted(declared))}"
            )
        binding = spec.binding
        values = dict(arguments)
        missing = [item for item in spec.parameters.get("required", ()) if item not in values]
        if missing:
            raise ValueError(f"{action} needs {', '.join(missing)}")
        path = str(binding["path"])
        for parameter in binding.get("path_params") or ():
            path = path.replace("{" + parameter + "}", str(values.pop(parameter)))
        query = {
            item: values.pop(item) for item in binding.get("query_params") or () if item in values
        }
        headers = {k: expand(v) for k, v in self.headers.items()}
        for item in binding.get("header_params") or ():
            if item in values:
                headers[item] = str(values.pop(item))
        body: Any = None
        fields = binding.get("body_fields")
        if fields is not None:
            body = {item: values.pop(item) for item in fields if item in values}
        elif "body" in values:
            body = values.pop("body")
        if values:
            raise ValueError(f"{action} does not take {', '.join(sorted(values))}")
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_seconds)
        url = self._base().rstrip("/") + "/" + path.lstrip("/")
        try:
            response = self._client.request(
                str(binding["method"]),
                url,
                params=query or None,
                headers=headers,
                json=body,
            )
        except httpx.HTTPError as exc:
            raise ValueError(f"{action} could not reach the API: {exc}") from exc
        if response.status_code >= 400:
            raise ValueError(f"HTTP {response.status_code}: {response.text[:2000]}")
        if not response.content:
            return {"status": response.status_code}
        try:
            parsed = response.json()
        except ValueError:
            return response.text
        if isinstance(parsed, dict):
            return parsed
        return {"items": parsed} if isinstance(parsed, list) else {"value": parsed}

    def reset(self, initial_state: Mapping[str, Any]) -> Any:
        """Run the ``reset`` command, if any.

        Returns:
            The command's output, or ``None``.
        """
        if not self.reset_command:
            return None
        output = run_hook(
            self.name,
            self.reset_command,
            stdin=json.dumps(dict(initial_state)),
            cwd=self.workspace,
            timeout=self.timeout_seconds,
        )
        return output.strip() or None

    def snapshot(self) -> Any:
        """Run the ``snapshot`` command.

        Returns:
            Its JSON output, or ``None`` without a snapshot command.
        """
        if not self.snapshot_command:
            return None
        output = run_hook(
            self.name,
            self.snapshot_command,
            stdin="",
            cwd=self.workspace,
            timeout=self.timeout_seconds,
        )
        return snapshot_output(self.name, output)

    def has_reset(self) -> bool:
        """Whether a reset command or Python override sets up each episode.

        Returns:
            True when episodes start from a known state.
        """
        return bool(self.reset_command) or type(self).reset is not OpenAPIApp.reset

    def has_snapshot(self) -> bool:
        """Whether a snapshot command or Python override reports state.

        Returns:
            True when the App can report its state.
        """
        return bool(self.snapshot_command) or type(self).snapshot is not OpenAPIApp.snapshot

    def is_local(self) -> bool:
        """Whether the API runs inside the Runtime.

        Returns:
            The ``local`` setting.
        """
        return self.local

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def _config(self) -> dict[str, Any]:
        config = super()._config()
        config.pop("actions", None)
        return config

    def _state_schema(self) -> dict[str, Any]:
        return {}


__all__ = ["OpenAPIApp", "load_document", "operation_actions"]
