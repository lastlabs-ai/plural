"""Copy a project Runtime's settings into an Environment's ``environment.yaml``.

An Environment revision is sealed: its content hash fixes how it behaves, so
the machine it runs on is part of the revision rather than a live link. Using a
project Runtime writes that Runtime's provider and settings into ``runtime:``,
with ``ref`` naming where they came from. Run it again after the Runtime
changes to pick the change up.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml

from plural.environments.definition import EnvironmentRuntime
from plural.project.layout import ENVIRONMENT, Project, ProjectError, ResourceRef
from plural.project.manifests import read_yaml_mapping
from plural.project.membership import _TOP_LEVEL_KEY
from plural.sandbox.catalog import settings_from_runtime


def runtime_block(runtime: EnvironmentRuntime, *, variables: Any = None) -> dict[str, Any]:
    """The ``runtime:`` mapping that reproduces ``runtime`` in a manifest.

    Returns:
        ``provider``, ``ref``, the provider's settings, then ``variables``.
    """
    block: dict[str, Any] = {"provider": runtime.provider}
    if runtime.ref:
        block["ref"] = runtime.ref
    block.update(settings_from_runtime(runtime))
    if variables:
        block["variables"] = variables
    return block


def use_runtime(project: Project, environment: str, runtime: Mapping[str, Any]) -> bool:
    """Replace an Environment's ``runtime:`` with a project Runtime's settings.

    The Environment's own ``variables`` are kept: they name values the
    Environment needs, which do not depend on where it runs.

    Args:
        project: The local project.
        environment: Environment name.
        runtime: The project Runtime's ``environment_runtime``, as the hosted
            service returns it.

    Returns:
        Whether the file changed.

    Raises:
        ProjectError: When the Environment does not exist locally.
    """
    ref = ResourceRef(ENVIRONMENT.name, environment)
    path = project.manifest_path(ref)
    if not path.is_file():
        raise ProjectError(
            f"No Environment named {environment!r} in this project. "
            f"Create it with `plural env init {environment}`."
        )
    current = read_yaml_mapping(path).get("runtime") or {}
    variables = current.get("variables") if isinstance(current, dict) else None
    resolved = EnvironmentRuntime.model_validate({**runtime, "variables": ()})
    block = runtime_block(resolved, variables=variables)
    if isinstance(current, dict) and current == block:
        return False
    text = yaml.safe_dump({"runtime": block}, sort_keys=False, allow_unicode=True)
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith("runtime:")), None)
    replacement = text.rstrip("\n").splitlines()
    if start is None:
        lines.extend(replacement)
    else:
        end = start + 1
        while end < len(lines):
            line = lines[end]
            stripped = line.strip()
            if _TOP_LEVEL_KEY.match(line) or (stripped.startswith("#") and not line[0].isspace()):
                break
            end += 1
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        lines[start:end] = replacement
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


__all__ = ["runtime_block", "use_runtime"]
