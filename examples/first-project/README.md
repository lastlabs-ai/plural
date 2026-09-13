# First Plural project

This support-ticket example uses Plural's typed Environment API, native model loop, and Job executor. It is independent of Wordle.

From an environment with the current Plural checkout installed:

```bash
python build.py
plural run job.yaml --dry-run
```

To execute, configure OPENAI_API_KEY for the model in agents/careful.yaml, then run:

```bash
plural run job.yaml --offline
```

This calls a model and can incur charges. Offline means local orchestration and storage, not no network. The local provider runs trusted code without isolation.

The complete explanation is in docs/tutorials/first-project.md in the package checkout. build.py rewrites generated YAML; edit it for reproducible changes.
