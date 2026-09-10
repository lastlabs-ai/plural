---
route: /docs/guides/production-to-dataset
title: "Turn production traffic into a dataset"
order: 350
description: "ds = Dataset.fromsink( \".plural/traces.jsonl\", name=\"prod-refunds-2026-w32\", version=\"2026.08.12\", where=lambda t: t.tags.get(\"intent\") == \"refund\" and t.outcome is not None, ) ds.save(\"data/prod-refunds-2026-w32.jsonl\") print(ds.contenthas"
audience: all
---
# Turn production traffic into a dataset

```python
from plural import Dataset

ds = Dataset.from_sink(
    ".plural/traces.jsonl",
    name="prod-refunds-2026-w32",
    version="2026.08.12",
    where=lambda t: t.tags.get("intent") == "refund" and t.outcome is not None,
)
ds.save("data/prod-refunds-2026-w32.jsonl")
print(ds.content_hash, len(ds))
```

This creates a **trace dataset** for analysis/export. It is not a benchmark
input. Unlabeled traces can also be useful for debugging; the outcome filter
here selects reviewed examples. To turn selected inputs into a regression
suite, create first-class Task revisions that pin independently reviewed
Verifier revisions and exact Environments. Follow the
[trace-to-task walkthrough](../tutorials/traces-and-datasets.md).
