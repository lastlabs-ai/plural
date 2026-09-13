# Wordle

The canonical public SDK example:

```bash
plural validate job.py:job
plural run job.py:job --dry-run
plural validate job.yaml
plural run job.yaml --dry-run
```

`environment.py`, `verifier.py`, `task.py`, `benchmark.py`, `agent.py`, and
`job.py` each create one public object. `job.yaml` is generated with:

```python
from plural.project import dump
from job import job

dump(job, "job.yaml")
```

`advanced.py` keeps the custom Harness, Agent/Human Verifiers, and Rewarder out
of the beginner flow.
