"""Render a portable API reference for both MkDocs and Plural Intel."""

import enum
import importlib
import inspect
import re
import sys
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    "plural.Client",
    "plural.types",
    "plural.Trace",
    "plural.TraceContext",
    "plural.tracing.resources.trace_json_schema",
    "plural.Job",
    "plural.Benchmark",
    "plural.project",
    "plural.JobStore",
    "plural.Environment",
    "plural.action",
    "plural.rewarder",
    "plural.environments.types",
    "plural.Harness",
    "plural.SandboxProvider",
    "plural.SandboxRequirements",
    "plural.ProviderRegistry",
    "plural.LocalProvider",
    "plural.DockerProvider",
    "plural.DaytonaProvider",
    "plural.routing.policies",
    "plural.environments.export.hf.to_huggingface_records",
    "plural.environments.export.verifiers.to_verifiers_trace",
    "plural.ModelCatalog",
    "plural.ModelSpec",
    "plural.estimate_cost",
    "plural.catalog.sync",
    "plural.TraceWriter",
    "plural.tracing.sinks",
    "plural.Redactor",
    "plural.providers",
    "plural.errors",
]


def _resolve(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        module, _, attr = name.rpartition(".")
        return getattr(importlib.import_module(module), attr)


def _signature(value):
    if inspect.isclass(value) and isinstance(value, enum.EnumMeta):
        # inspect.signature() spells the Enum constructor differently before
        # Python 3.12; pin the modern form so generated docs are portable.
        return "(*values)"
    try:
        s = str(inspect.signature(value))
    except (ValueError, TypeError):
        return ""
    s = re.sub(r"<[^<>]* at 0x[0-9a-f]+>", "<configured default>", s)
    # Absolute paths in defaults (e.g. PosixPath('/.../models.json')) depend on
    # where the source tree lives, so mask them to keep generated docs portable.
    s = re.sub(r"\b(PosixPath|WindowsPath|Path)\('[^']*'\)", r"\1('<default>')", s)
    return s


lines = [
    "---",
    "route: /docs/reference/api",
    'title: "API reference"',
    "order: 240",
    'description: "Supported public Python API signatures from the current source."',
    "audience: all",
    "nav: false",
    "nav_group: Reference",
    "---",
    "# API reference",
    "",
    "Start with [the support queue tutorial](../tutorials/support-queue.md) for "
    "complete working code. Use the [field catalog](fields.md) for definition "
    "fields, defaults, and constraints. This reference is generated from supported "
    "root APIs and public extension modules. Planner and executor implementation "
    "types such as `JobRunner`, `JobSpec`, and `TrialSpec` are intentionally omitted.",
    "",
    "Model constructors are described by their field contracts rather than "
    "duplicating long generated signatures. Methods below are defined on the "
    "listed class; ordinary inherited Pydantic methods are not repeated.",
    "",
    "`Client` provider adapters are the application inference API. Public `Job` "
    "native execution is a separate OpenAI-compatible chat-completions path.",
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
output = ROOT / "docs/reference/api.md"
content = "\n".join(lines).rstrip() + "\n"
if "--check" in sys.argv:
    if output.read_text(encoding="utf-8") != content:
        raise SystemExit("Generated API documentation is stale.")
else:
    output.write_text(content, encoding="utf-8")
print(f"Generated API documentation for {len(seen)} public symbols.")
