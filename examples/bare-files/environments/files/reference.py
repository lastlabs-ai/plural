"""The reference policy: what a careful person would do with the invoices.

`plural task validate` plays it through the normal engine, so a Task whose reference
fails has a broken Task or a broken grader. It reads only what an Agent reads.
"""

import csv
from decimal import Decimal
from pathlib import Path


def solve(task, environment):
    """Total March's invoices into march-total.txt, report the write, and answer."""
    found = sorted(Path("..", "resources").rglob("invoices.csv"))
    if not found:
        raise FileNotFoundError("invoices.csv is not in ../resources")
    invoices = found[0]
    with invoices.open(newline="") as handle:
        total = sum(
            Decimal(row["amount_usd"])
            for row in csv.DictReader(handle)
            if row["date"].startswith("2026-03")
        )
    text = f"{total:.2f}"
    Path("march-total.txt").write_text(text + "\n")
    environment.record_tool("Write", {"file_path": "march-total.txt"}, output=text)
    return f"The March 2026 total is {text}."
