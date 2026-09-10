"""Hosted agent instance types."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentModel(BaseModel):
    """Strict hosted agent value."""

    model_config = ConfigDict(extra="forbid")


class AgentMemory(AgentModel):
    """One memory written onto a persistent agent instance."""

    memory_id: str
    instance_id: str
    kind: str
    content: Any
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_trial_id: str | None = None
    created_at: datetime | None = None


class AgentSkill(AgentModel):
    """A named skill the instance has learned or been given."""

    name: str
    description: str = ""
    instructions: str = ""
    action_names: tuple[str, ...] = ()
    origin: str = "user"
    updated_at: datetime | None = None


class AgentArtifact(AgentModel):
    """A file or structured blob stored on the instance."""

    name: str
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    checksum: str = ""
    object_key: str = ""


class AgentExperience(AgentModel):
    """Read-only counters accumulated by running in environments."""

    trial_count: int = 0
    task_count: int = 0
    mean_reward: float | None = None
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    last_trial_at: datetime | None = None


class AgentInstance(AgentModel):
    """A live agent instance bound to one template revision."""

    id: str
    template_id: str
    template_revision_id: str | None = None
    name: str
    slug: str = ""
    status: Literal["active", "archived"] = "active"
    experience: AgentExperience = Field(default_factory=AgentExperience)
    created_at: datetime | None = None
    updated_at: datetime | None = None
