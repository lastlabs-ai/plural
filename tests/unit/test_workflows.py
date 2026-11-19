"""The sandbox image workflow runs on a pinned runner with actions off Node 20."""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/sandbox-image.yml"

# The first major version of each action that runs on Node 24.
NODE24 = {
    "actions/checkout": 5,
    "docker/setup-buildx-action": 4,
    "docker/build-push-action": 7,
    "docker/login-action": 4,
}


def test_the_sandbox_image_workflow_is_pinned_and_off_node_20() -> None:
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    for job in jobs.values():
        assert job["runs-on"] == "ubuntu-24.04"
        actions = [step["uses"] for step in job["steps"] if "uses" in step]
        assert actions
        for action in actions:
            name, _, ref = action.partition("@")
            assert name in NODE24, f"{name} has no known Node 24 version"
            assert int(ref.lstrip("v").split(".")[0]) >= NODE24[name], action
