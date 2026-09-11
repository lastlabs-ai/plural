"""First-class schema-v2 Task and Benchmark definitions."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from plural.common import FrozenModel, content_hash, stable_id
from plural.environments.definition import EnvironmentDefinition
from plural.evidence import validate_evidence_contract
from plural.verifiers import WeightedVerifier


class TaskDefinition(FrozenModel):
    """First-class Task revision pinned to one Environment and Verifiers."""

    schema_version: Literal["2"] = "2"
    task_id: str = Field(min_length=1)
    revision: str = Field(default="0.1.0", min_length=1)
    instructions: str = Field(min_length=1)
    environment: EnvironmentDefinition
    verifiers: tuple[WeightedVerifier, ...] = Field(min_length=1)
    info: Any = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _evidence_fits_environment(self) -> TaskDefinition:
        errors: list[str] = []
        for binding in self.verifiers:
            errors.extend(
                validate_evidence_contract(
                    self.environment.name,
                    self.environment.observation_schema,
                    self.environment.state_schema,
                    binding.verifier.evidence,
                )
            )
        if errors:
            raise ValueError("; ".join(errors))
        return self

    @property
    def public_payload(self) -> dict[str, Any]:
        """Task fields visible to an Agent."""
        return {
            "task_id": self.task_id,
            "instructions": self.instructions,
            "info": self.info,
            "metadata": self.metadata,
        }

    @property
    def content_hash(self) -> str:
        """Stable Task revision digest."""
        return content_hash(self)

    @property
    def identity(self) -> str:
        """Stable Task revision identifier."""
        return stable_id("tsk", self)


class BenchmarkDefinition(FrozenModel):
    """A revisioned ordered selection of Tasks across Environments."""

    schema_version: Literal["2"] = "2"
    name: str = Field(min_length=1)
    revision: str = Field(default="0.1.0", min_length=1)
    tasks: tuple[TaskDefinition, ...] = Field(min_length=1)
    primary_metric: str = "reward"
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique_tasks(self) -> BenchmarkDefinition:
        identities = [task.identity for task in self.tasks]
        if len(identities) != len(set(identities)):
            raise ValueError("benchmark Task revisions must be unique")
        return self

    @property
    def content_hash(self) -> str:
        """Stable Benchmark revision digest."""
        return content_hash(self)

    @property
    def benchmark_id(self) -> str:
        """Stable Benchmark revision identifier."""
        return stable_id("bmk", self)


__all__ = ["BenchmarkDefinition", "TaskDefinition"]
