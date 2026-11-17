"""Check the answer and the file the Agent wrote, against the Task's answer key."""

from __future__ import annotations

import re

from plural import Episode, VerifierOutput


def check(episode: Episode) -> VerifierOutput:
    """Score 1 when both the answer and ``march-total.txt`` give the March total."""
    expected = episode.expected or {}
    total = str(expected.get("total_usd", ""))
    name = str(expected.get("file", "march-total.txt"))
    answer = str(episode.answer or "").replace(",", "")
    answered = total in re.findall(r"\d+(?:\.\d+)?", answer)
    found = episode.workspace.list(f"**/{name}") if episode.workspace.available else []
    written = any(episode.workspace.read(path).strip() == total for path in found)
    return VerifierOutput(
        score=(float(answered) + float(written)) / 2,
        metrics={"answer_correct": float(answered), "file_correct": float(written)},
        feedback=(
            f"answer {'gives' if answered else 'lacks'} {total}; "
            + (
                f"{found[0]} {'holds' if written else 'does not hold'} it"
                if found
                else f"no {name}"
            )
        ),
    )
