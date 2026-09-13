"""Render a portable API reference for both MkDocs and Plural Intel."""

import importlib
import inspect
import re
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    "plural.client.Client",
    "plural.types",
    "plural.tracing.schema.Trace",
    "plural.tracing.schema.TraceContext",
    "plural.tracing.resources.trace_json_schema",
    "plural.execution.engine.Job",
    "plural.execution.engine.Trial",
    "plural.execution.store.JobStore",
    "plural.environments.env.Environment",
    "plural.environments.env.action",
    "plural.environments.env.rewarder",
    "plural.environments.types",
    "plural.harness.models",
    "plural.sandbox.base.SandboxProvider",
    "plural.sandbox.models",
    "plural.sandbox.registry.ProviderRegistry",
    "plural.sandbox.local.LocalProvider",
    "plural.sandbox.docker.DockerProvider",
    "plural.sandbox.daytona.DaytonaProvider",
    "plural.cli.config",
    "plural.cli.auth",
    "plural.routing.policies",
    "plural.environments.export.hf.to_huggingface_records",
    "plural.environments.export.verifiers.to_verifiers_trace",
    "plural.catalog.models.ModelCatalog",
    "plural.catalog.models.ModelSpec",
    "plural.catalog.models.estimate_cost",
    "plural.catalog.sync",
    "plural.tracing.writer.TraceWriter",
    "plural.tracing.sinks",
    "plural.tracing.redaction",
    "plural.providers.base",
    "plural.errors",
]


def _resolve(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        module, _, attr = name.rpartition(".")
        return getattr(importlib.import_module(module), attr)


def _signature(value):
    try:
        s = str(inspect.signature(value))
    except (ValueError, TypeError):
        return ""
    s = re.sub(r"<[^<>]* object at 0x[0-9a-f]+>", "<configured default>", s)
    return s


lines = [
    "---",
    "route: /docs/reference/api",
    'title: "API reference"',
    "order: 240",
    'description: "Python API signatures and documentation from the current source."',
    "audience: all",
    "nav: false",
    "---",
    "# API reference",
    "",
    "Start with [the project walkthrough](../tutorials/first-project.md) for "
    "complete working code. Use the [field catalog](fields.md) for definition "
    "fields, defaults, and constraints. This reference is generated from the "
    "current package and is identical on both documentation surfaces.",
    "",
    "Model constructors are described by their field contracts rather than "
    "duplicating long generated signatures. Methods below are defined on the "
    "listed class; ordinary inherited Pydantic methods are not repeated.",
    "",
]
seen = set()


def _documentation(value):
    text = inspect.getdoc(value) or "No additional docstring is defined."
    # Preserve exact source documentation without pretending Google-style indents are Markdown
    # lists.
    first, *rest = text.split("\n\n", 1)
    lines.extend([" ".join(first.splitlines()), ""])
    if rest:
        lines.extend(["```text", rest[0], "```", ""])


def _emit(name, value):
    if name in seen:
        return
    seen.add(name)
    lines.extend([f"## {name}", ""])
    _documentation(value)
    if inspect.isclass(value):
        if not issubclass(value, BaseModel):
            lines.extend(["```python", name + _signature(value), "```", ""])
        for member, raw in value.__dict__.items():
            if member.startswith("_") or member == "definition":
                continue
            fn = raw.__func__ if isinstance(raw, (classmethod, staticmethod)) else raw
            if not inspect.isfunction(fn):
                continue
            lines.extend(
                [
                    f"### {name}.{member}",
                    "",
                    "```python",
                    member + _signature(getattr(value, member)),
                    "```",
                    "",
                ]
            )
            _documentation(fn)
    else:
        lines.extend(["```python", name + _signature(value), "```", ""])


for name in TARGETS:
    value = _resolve(name)
    if inspect.ismodule(value):
        exported = getattr(value, "__all__", None)
        for key, item in sorted(vars(value).items()):
            if key.startswith("_") or not (inspect.isclass(item) or inspect.isfunction(item)):
                continue
            if exported is not None:
                if key not in exported:
                    continue
            elif getattr(item, "__module__", None) != value.__name__:
                continue
            _emit(getattr(item, "__module__", name) + "." + getattr(item, "__name__", key), item)
    else:
        _emit(name, value)
(ROOT / "docs/reference/api.md").write_text("\n".join(lines).rstrip() + "\n")
print(f"Generated API documentation for {len(seen)} public symbols.")
