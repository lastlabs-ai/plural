"""Stable, address-free fingerprint helpers for configured Python objects."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import math
import textwrap
import types
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def stable_fingerprint_value(value: Any, *, _seen: set[int] | None = None) -> Any:
    """Return a deterministic representation without object addresses."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        return {"float": str(value)}
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, Path):
        return {"path": value.as_posix()}
    if isinstance(value, Enum):
        return {
            "enum": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": stable_fingerprint_value(value.value, _seen=_seen),
        }
    if isinstance(value, types.CodeType):
        return code_fingerprint_payload(value)

    seen = _seen if _seen is not None else set()
    value_id = id(value)
    value_type = type(value)
    type_name = f"{value_type.__module__}.{value_type.__qualname__}"
    if value_id in seen:
        return {"recursive": type_name}
    seen.add(value_id)
    try:
        if isinstance(value, (list, tuple)):
            return [stable_fingerprint_value(item, _seen=seen) for item in value]
        if isinstance(value, (set, frozenset)):
            items = [stable_fingerprint_value(item, _seen=seen) for item in value]
            return sorted(items, key=_canonical_json)
        if isinstance(value, dict):
            items = [
                (
                    stable_fingerprint_value(key, _seen=seen),
                    stable_fingerprint_value(item, _seen=seen),
                )
                for key, item in value.items()
            ]
            return {"items": sorted(items, key=lambda item: _canonical_json(item[0]))}
        if isinstance(value, BaseModel):
            config = {
                name: stable_fingerprint_value(getattr(value, name), _seen=seen)
                for name in type(value).model_fields
                if not name.startswith("_")
            }
            return {"type": type_name, "config": config}
        if is_dataclass(value) and not isinstance(value, type):
            config = {
                field.name: stable_fingerprint_value(getattr(value, field.name), _seen=seen)
                for field in fields(value)
                if not field.name.startswith("_")
            }
            return {"type": type_name, "config": config}
        return {"type": type_name}
    finally:
        seen.remove(value_id)


def public_configuration(value: Any) -> dict[str, Any]:
    """Capture stable dataclass, Pydantic, or instance configuration.

    Returns:
        Stable behavior-affecting field values keyed by name.
    """
    values: dict[str, Any] = {}
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            if not _is_internal_attribute(name):
                values[name] = getattr(value, name)
        private_attributes = getattr(type(value), "__private_attributes__", {})
        if isinstance(private_attributes, dict):
            for name in private_attributes:
                if _is_internal_attribute(name):
                    continue
                try:
                    values[name] = getattr(value, name)
                except (AttributeError, TypeError):
                    continue
    elif is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            if not _is_internal_attribute(field.name):
                values[field.name] = getattr(value, field.name)

    try:
        namespace = object.__getattribute__(value, "__dict__")
    except (AttributeError, TypeError):
        namespace = None
    if isinstance(namespace, dict):
        values.update(
            {
                name: item
                for name, item in namespace.items()
                if isinstance(name, str) and not _is_internal_attribute(name)
            }
        )

    for name, item in _slot_values(value):
        values.setdefault(name, item)
    return {name: stable_fingerprint_value(item) for name, item in sorted(values.items())}


def _is_internal_attribute(name: str) -> bool:
    """Return whether an attribute is interpreter/framework bookkeeping."""
    return name.startswith("__") and name.endswith("__")


def _slot_values(value: Any) -> list[tuple[str, Any]]:
    """Read initialized instance slots across the MRO without invoking properties.

    Returns:
        Initialized slot names and values.
    """
    values: list[tuple[str, Any]] = []
    for owner in type(value).__mro__:
        slots = owner.__dict__.get("__slots__", ())
        if isinstance(slots, str):
            slot_names = (slots,)
        elif isinstance(slots, dict):
            slot_names = tuple(slots)
        else:
            try:
                slot_names = tuple(slots)
            except TypeError:
                continue
        for declared_name in slot_names:
            if not isinstance(declared_name, str) or declared_name in {"__dict__", "__weakref__"}:
                continue
            name = declared_name
            if name.startswith("__") and not name.endswith("__"):
                owner_name = owner.__name__.lstrip("_")
                name = f"_{owner_name}{name}"
            if _is_internal_attribute(name):
                continue
            descriptor = owner.__dict__.get(name)
            if descriptor is None or not (
                inspect.ismemberdescriptor(descriptor) or inspect.isgetsetdescriptor(descriptor)
            ):
                continue
            try:
                item = descriptor.__get__(value, type(value))
            except (AttributeError, TypeError):
                continue
            values.append((name, item))
    return values


def code_fingerprint_payload(code: types.CodeType) -> dict[str, Any]:
    """Serialize executable code without source paths or line numbers.

    Returns:
        Stable executable code metadata.
    """
    return {
        "argcount": code.co_argcount,
        "posonlyargcount": getattr(code, "co_posonlyargcount", 0),
        "kwonlyargcount": code.co_kwonlyargcount,
        "flags": code.co_flags,
        "bytecode": code.co_code.hex(),
        "constants": [stable_fingerprint_value(item) for item in code.co_consts],
        "names": list(code.co_names),
        "varnames": list(code.co_varnames),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
    }


def callable_implementation_digest(fn: Any) -> str:
    """Hash callable implementation and stable callable-object configuration.

    Returns:
        Hex SHA256 digest.
    """
    target = inspect.unwrap(fn)
    callable_instance: Any = None
    if inspect.ismethod(target):
        target = target.__func__
    elif not inspect.isroutine(target) and callable(target):
        callable_instance = target
        target = inspect.unwrap(type(target).__call__)

    payload: dict[str, Any] = {
        "module": getattr(target, "__module__", None),
        "qualname": getattr(target, "__qualname__", getattr(target, "__name__", None)),
        "defaults": stable_fingerprint_value(getattr(target, "__defaults__", None)),
        "kwdefaults": stable_fingerprint_value(getattr(target, "__kwdefaults__", None)),
    }
    if callable_instance is not None:
        instance_type = type(callable_instance)
        payload["callable_type"] = f"{instance_type.__module__}.{instance_type.__qualname__}"
        payload_hook = getattr(callable_instance, "fingerprint_payload", None)
        payload["configuration"] = (
            stable_fingerprint_value(payload_hook())
            if callable(payload_hook)
            else public_configuration(callable_instance)
        )
    try:
        source = textwrap.dedent(inspect.getsource(target))
        payload["source"] = ast.dump(ast.parse(source), include_attributes=False)
    except (OSError, TypeError, IndentationError, SyntaxError):
        code = getattr(target, "__code__", None)
        if isinstance(code, types.CodeType):
            payload["code"] = code_fingerprint_payload(code)

    closure = getattr(target, "__closure__", None)
    if closure:
        closure_values: list[Any] = []
        for cell in closure:
            try:
                closure_values.append(stable_fingerprint_value(cell.cell_contents))
            except ValueError:
                closure_values.append({"empty_cell": True})
        payload["closure"] = closure_values
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
