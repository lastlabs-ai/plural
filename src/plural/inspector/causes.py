"""The cause dimensions a Finding names.

The built-in dimensions are data, in ``causes.yaml`` beside this module. A
project adds its own, or rewords a built-in one, in ``inspector/causes.yaml``:

.. code-block:: yaml

    - name: retrieval
      agent: true
      description: The search index returned the wrong documents.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import Field

from plural.common import FrozenModel

CAUSES_FILE = "causes.yaml"
"""The file, in a project's ``inspector`` folder, that adds cause dimensions."""

INSPECTOR_DIR = "inspector"
"""The project folder holding the Inspector's project files: causes, patterns, signals."""


class Cause(FrozenModel):
    """One cause dimension.

    Attributes:
        name: The dimension's name, such as ``tools``.
        description: What the dimension covers, as the Inspector is told it.
        agent: Whether a change to the Agent can fix the cause, so a fork that
            makes the change can confirm it.
    """

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str = Field(min_length=1)
    agent: bool = False


def builtin_causes() -> tuple[Cause, ...]:
    """The dimensions Plural ships.

    Returns:
        The causes, in their file's order.
    """
    return _read(Path(__file__).with_name(CAUSES_FILE))


def load_causes(project_root: Path | None = None) -> tuple[Cause, ...]:
    """The built-in dimensions, with a project's own added or reworded.

    Returns:
        The causes: the built-in ones in order, a reworded one in its place,
        then the project's new ones.

    Raises:
        ValueError: When the project's file isn't a list of causes.
    """
    causes = {item.name: item for item in builtin_causes()}
    if project_root is not None:
        path = project_root / INSPECTOR_DIR / CAUSES_FILE
        if path.is_file():
            for item in _read(path):
                causes[item.name] = item
    return tuple(causes.values())


def _read(path: Path) -> tuple[Cause, ...]:
    payload = yaml.safe_load(path.read_text("utf-8")) or []
    if not isinstance(payload, list):
        raise ValueError(f"{path} must be a list of causes, each with a name and description.")
    try:
        return tuple(Cause.model_validate(item) for item in payload)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from None


__all__ = ["CAUSES_FILE", "INSPECTOR_DIR", "Cause", "builtin_causes", "load_causes"]
