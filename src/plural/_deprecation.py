"""Deprecated names kept working for one release after a rename."""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping
from typing import Any


def warn_renamed(old: str, new: str, *, stacklevel: int = 3) -> None:
    """Warn that ``old`` was renamed to ``new``."""
    warnings.warn(
        f"{old} is deprecated and will be removed in the next release; use {new}.",
        DeprecationWarning,
        stacklevel=stacklevel,
    )


def renamed_keys(value: Any, renames: Mapping[str, str], owner: str) -> Any:
    """Move each old key in a mapping to its new name, warning once per key.

    Returns:
        ``value`` unchanged when it is not a mapping or uses no old key;
        otherwise a copy with the new keys.

    Raises:
        ValueError: When a mapping gives both an old key and its new name.
    """
    if not isinstance(value, Mapping) or not any(old in value for old in renames):
        return value
    payload = dict(value)
    for old, new in renames.items():
        if old not in payload:
            continue
        if new in payload:
            raise ValueError(f"{owner} gives both {new} and its old name {old}; keep {new}")
        warn_renamed(f"{owner}.{old}", f"{owner}.{new}", stacklevel=4)
        payload[new] = payload.pop(old)
    return payload


def renamed_attribute(old: str, new: str) -> Any:
    """A read-only property under ``old`` that warns and returns ``new``.

    Returns:
        A property for the class body.
    """

    def get(self: Any) -> Any:
        warn_renamed(f"{type(self).__name__}.{old}", f"{type(self).__name__}.{new}")
        return getattr(self, new)

    return property(get, doc=f"Deprecated: use ``{new}``.")


def module_getattr(
    module: str, renames: Mapping[str, tuple[str, Callable[[], Any]]]
) -> Callable[[str], Any]:
    """A module ``__getattr__`` resolving old names to their replacements.

    Args:
        module: The module's import name, for messages.
        renames: Old name to its new name and a loader for the new object.

    Returns:
        The ``__getattr__`` function to assign in the module.
    """

    def __getattr__(name: str) -> Any:
        renamed = renames.get(name)
        if renamed is None:
            raise AttributeError(f"module {module!r} has no attribute {name!r}")
        new, load = renamed
        warn_renamed(f"{module}.{name}", f"{module}.{new}")
        return load()

    return __getattr__


__all__ = ["module_getattr", "renamed_attribute", "renamed_keys", "warn_renamed"]
