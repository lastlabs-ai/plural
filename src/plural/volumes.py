"""Slots for an Agent's Volume, its persistent memory, which is not built yet.

A Volume is versioned like a workspace snapshot: each version is immutable,
and a Trial reads one version and may write the next. Until Volumes exist every
slot here is ``None``, and a ``None`` slot changes no hash, so records written
before and after it are identical.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

MEMORY_MOUNT = "/memory"
"""Where a Volume will be mounted for the Agent. Reserved: nothing else may use it."""


class VolumeVersion(BaseModel):
    """One immutable version of one Volume, as a memory provider names it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, description="The memory provider, such as plural.")
    volume_id: str = Field(min_length=1, description="The Volume, as the provider names it.")
    version: str = Field(min_length=1, description="The version, as the provider names it.")


__all__ = ["MEMORY_MOUNT", "VolumeVersion"]
