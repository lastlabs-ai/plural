"""Score 1 when the Agent wrote the expected file, whatever it answered."""

from __future__ import annotations

from plural import Episode, VerifierOutput


def check(episode: Episode) -> VerifierOutput:
    """Score 1 when ``smoke.txt`` holds the expected text."""
    expected = episode.expected or {}
    name, text = str(expected["file"]), str(expected["text"])
    found = episode.workspace.list(f"**/{name}") if episode.workspace.available else []
    written = any(episode.workspace.read(path).strip() == text for path in found)
    return VerifierOutput(
        score=float(written),
        metrics={"file_written": float(written)},
        evidence=[f"{name} found at {', '.join(found) or 'no path'}"],
        feedback=f"{name} {'holds' if written else 'is missing or does not hold'} {text}",
    )
