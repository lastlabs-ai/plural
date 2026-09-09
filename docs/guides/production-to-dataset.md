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
suite, create explicit `TaskData` records with independently reviewed expected
answers, then save a `TaskDataset`. Follow the
[trace-to-task walkthrough](../tutorials/traces-and-datasets.md).
