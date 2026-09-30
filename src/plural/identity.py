"""Revision identity: the content hash every Plural SDK and the service compute alike.

A revision's content hash names what it contains and nothing else. Labels a
person chooses (``name``, ``title``, ``version``) are left out, so renaming a
resource, labeling a release, or forking it into another project keeps the
hash. Dependencies enter by their own content hashes, so a Benchmark's hash
covers every Task, Environment, and Verifier beneath it.

The rules are language-neutral and specified in
``docs/architecture/revision-identity.md``; ``spec/identity/vectors.json``
holds cases every implementation must reproduce.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic_core import to_jsonable_python

IDENTITY_SCHEME = 2
"""Version of these rules, hashed into every digest so a rule change can never collide."""

LABEL_FIELDS = frozenset({"name", "title", "version", "revision"})
"""Top-level fields that label a revision rather than describe its content."""

UNORDERED_FIELDS = frozenset(
    {
        "allowed_capabilities",
        "allowed_harness_capabilities",
        "allowed_targets",
        "capabilities",
        "declared",
        "denied",
        "denied_capabilities",
        "enforced",
        "extra_capabilities",
        "granted",
        "granted_harness_capabilities",
        "targets",
    }
)
"""Fields, at any depth, whose arrays are sets: sorted by their canonical JSON before hashing."""

SEALED_KINDS = frozenset({"environment", "verifier", "task", "harness", "benchmark"})
"""Kinds whose hash fixes their behavior. An Agent names a hosted model, so it is referenced."""


def canonical_json(value: Any) -> str:
    """Serialize JSON data per RFC 8785 (JSON Canonicalization Scheme).

    Object keys are sorted by UTF-16 code units, strings escape only what JSON
    requires, and numbers use the shortest ECMAScript form, so ``1.0`` and
    ``1`` serialize alike. Integers are written exactly; keep them within
    ±(2**53 - 1) so every language reads them the same.

    Returns:
        The canonical text, to be hashed as UTF-8.

    Raises:
        ValueError: For NaN, infinity, or a value that is not JSON data.
    """
    parts: list[str] = []
    _encode(value, parts)
    return "".join(parts)


def revision_hash(kind: str, content: Mapping[str, Any]) -> str:
    """The content hash of one revision of ``kind``.

    Args:
        kind: ``environment``, ``verifier``, ``task``, ``harness``, ``agent``,
            or ``benchmark``.
        content: The revision's canonical definition. Top-level label fields
            are dropped here; dependencies must already be content hashes.

    Returns:
        ``sha256:`` and 64 lowercase hex characters.
    """
    body = {key: item for key, item in content.items() if key not in LABEL_FIELDS}
    data = to_jsonable_python(body, exclude_none=False)
    payload = {"identity": IDENTITY_SCHEME, "kind": kind, "content": _sort_sets(data)}
    return f"sha256:{hashlib.sha256(canonical_json(payload).encode('utf-8')).hexdigest()}"


def is_sealed(kind: str) -> bool:
    """Whether a revision of ``kind`` behaves the same every time it runs.

    Returns:
        ``True`` for kinds whose content hash fixes their behavior.
    """
    return kind in SEALED_KINDS


def _sort_sets(value: Any) -> Any:
    if isinstance(value, Mapping):
        payload = {key: _sort_sets(item) for key, item in value.items()}
        for key in UNORDERED_FIELDS & set(payload):
            if isinstance(payload[key], list):
                payload[key] = sorted(payload[key], key=canonical_json)
        return payload
    if isinstance(value, (list, tuple)):
        return [_sort_sets(item) for item in value]
    return value


def _encode(value: Any, parts: list[str]) -> None:
    if value is None:
        parts.append("null")
    elif value is True:
        parts.append("true")
    elif value is False:
        parts.append("false")
    elif isinstance(value, int):
        parts.append(str(value))
    elif isinstance(value, float):
        parts.append(_number(value))
    elif isinstance(value, str):
        parts.append(_string(value))
    elif isinstance(value, Mapping):
        keys = list(value)
        if not all(isinstance(key, str) for key in keys):
            raise ValueError("canonical JSON object keys must be strings")
        parts.append("{")
        for index, key in enumerate(sorted(keys, key=lambda item: item.encode("utf-16-be"))):
            if index:
                parts.append(",")
            parts.append(_string(key))
            parts.append(":")
            _encode(value[key], parts)
        parts.append("}")
    elif isinstance(value, (list, tuple)):
        parts.append("[")
        for index, item in enumerate(value):
            if index:
                parts.append(",")
            _encode(item, parts)
        parts.append("]")
    else:
        raise ValueError(f"{type(value).__name__} is not JSON data")


_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\f": "\\f",
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _string(value: str) -> str:
    out = ['"']
    for char in value:
        escaped = _ESCAPES.get(char)
        if escaped is not None:
            out.append(escaped)
        elif char < " ":
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _number(value: float) -> str:
    """ECMAScript ``Number.prototype.toString`` for a finite double.

    Returns:
        The shortest text that reads back as ``value``.

    Raises:
        ValueError: For NaN or infinity.
    """
    if not math.isfinite(value):
        raise ValueError("canonical JSON cannot represent NaN or infinity")
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    _sign, digit_tuple, exponent = Decimal(repr(abs(value))).normalize().as_tuple()
    assert isinstance(exponent, int)
    digits = "".join(str(digit) for digit in digit_tuple)
    k = len(digits)
    n = exponent + k
    if k <= n <= 21:
        text = digits + "0" * (n - k)
    elif 0 < n <= 21:
        text = f"{digits[:n]}.{digits[n:]}"
    elif -6 < n <= 0:
        text = f"0.{'0' * -n}{digits}"
    else:
        power = n - 1
        mantissa = digits if k == 1 else f"{digits[0]}.{digits[1:]}"
        text = f"{mantissa}e{'+' if power >= 0 else '-'}{abs(power)}"
    return sign + text


__all__ = [
    "IDENTITY_SCHEME",
    "LABEL_FIELDS",
    "SEALED_KINDS",
    "UNORDERED_FIELDS",
    "canonical_json",
    "is_sealed",
    "revision_hash",
]
