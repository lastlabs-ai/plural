"""Portable session snapshot bundles."""

from __future__ import annotations

from pathlib import Path

from plural.sessions import (
    SessionSnapshot,
    export_from_parts,
    export_from_trial,
    import_bundle,
)


class _StubResourceAPI:
    def __init__(self, parents: list[dict]) -> None:
        self._parents = parents

    def list(self) -> dict:
        return {"items": self._parents}

    def revisions(self, resource_id: str) -> dict:
        parent = next(item for item in self._parents if item["id"] == resource_id)
        return {"items": parent["revisions"]}


class _StubTracesAPI:
    def __init__(self, traces: list[dict]) -> None:
        self._traces = traces

    def list(self, **params: object) -> dict:
        assert params.get("trial_id") == "trial-1"
        return {"items": self._traces}


class _StubStudio:
    def __init__(self) -> None:
        self.trials = self
        self.agents = _StubResourceAPI(
            [
                {
                    "id": "agent-1",
                    "revisions": [
                        {
                            "id": "agent-rev-1",
                            "definition": {"name": "Solver", "model": "m"},
                        }
                    ],
                }
            ]
        )
        self.environments = _StubResourceAPI(
            [
                {
                    "id": "env-1",
                    "revisions": [{"id": "env-rev-1", "definition": {"name": "Support"}}],
                }
            ]
        )
        self.tasks = _StubResourceAPI(
            [
                {
                    "id": "task-1",
                    "revisions": [
                        {
                            "id": "task-rev-1",
                            "definition": {"resources": [{"path": "data/ticket.json"}]},
                        }
                    ],
                }
            ]
        )
        self.traces = _StubTracesAPI(
            [{"id": "trace-1", "state": {"ticket": 42}}, {"id": "trace-2"}]
        )

    def get(self, trial_id: str) -> dict:
        assert trial_id == "trial-1"
        return {
            "id": "trial-1",
            "job_id": "job-1",
            "agent_revision_id": "agent-rev-1",
            "environment_revision_id": "env-rev-1",
            "task_revision_id": "task-rev-1",
            "agent_name": "Solver",
        }


def test_bundle_roundtrip_preserves_snapshot(tmp_path: Path) -> None:
    snapshot = export_from_parts(
        "support",
        agent={"name": "Solver", "model": "m"},
        environment={"name": "Support"},
        state={"ticket": 42},
        data=["data/ticket.json"],
    )
    bundle = snapshot.save(tmp_path / "bundle")
    assert (bundle / "agent.yaml").exists()
    assert (bundle / "environment.yaml").exists()
    assert (bundle / "state.json").exists()
    assert (bundle / "manifest.json").exists()

    loaded = SessionSnapshot.load(bundle)
    assert loaded.name == "support"
    assert loaded.agent == {"name": "Solver", "model": "m"}
    assert loaded.environment == {"name": "Support"}
    assert loaded.state == {"ticket": 42}
    assert loaded.data == ["data/ticket.json"]
    assert loaded.provenance.source == "local"


def test_export_from_trial_captures_provenance_and_state() -> None:
    snapshot = export_from_trial(_StubStudio(), "trial-1")  # type: ignore[arg-type]
    assert snapshot.agent == {"name": "Solver", "model": "m"}
    assert snapshot.environment == {"name": "Support"}
    assert snapshot.state == {"ticket": 42}
    assert snapshot.data == ["data/ticket.json"]
    assert snapshot.provenance.source == "trial"
    assert snapshot.provenance.trial_id == "trial-1"
    assert snapshot.provenance.job_id == "job-1"


def test_import_redeploys_separate_instance(tmp_path: Path) -> None:
    bundle = export_from_parts(
        "support",
        agent={"name": "Solver"},
        environment={"name": "Support"},
    ).save(tmp_path / "bundle")

    first = import_bundle(bundle, tmp_path / "instances")
    second = import_bundle(bundle, tmp_path / "instances")
    assert first != second
    assert (first / "instance.json").exists()
    assert SessionSnapshot.load(first).agent == {"name": "Solver"}
    assert SessionSnapshot.load(second).environment == {"name": "Support"}
