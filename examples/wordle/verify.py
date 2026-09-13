import json
from pathlib import Path

payload = json.loads(Path(".plural/verifier-input.json").read_text())
view = payload["environment_view"]
solved = bool(view["observation"].get("solved") or view["state"].get("solved"))
Path("verifier-result.json").write_text(
    json.dumps(
        {
            "reward": float(solved),
            "scores": {"solved": float(solved)},
            "evidence": [view["observation"].get("text", "")],
        }
    )
    + "\n"
)
