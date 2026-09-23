# Maintaining the documentation

`docs/` is the canonical shared documentation. Plural Intel copies it with
`python3 scripts/sync_plural_docs.py` from the sibling lastlabs repository.
Intel-only usage and membership guides stay in that application's `intel-docs` directory.

After changing package models, commands, or public APIs, run from this repository:

```bash
python scripts/generate_docs_fields.py
python scripts/generate_docs_api.py
python scripts/generate_cli_reference.py
```

The first-project tutorial walks through `examples/first-project`, a project in the
standard layout. After changing any file in it, refresh the download:

```bash
python scripts/sync_docs_starter.py
```

Verify before synchronizing the site:

```bash
python scripts/check_docs.py
python scripts/generate_cli_reference.py --check
python scripts/sync_docs_starter.py --check
python scripts/check_docs_starter.py
mkdocs build --strict
```

The starter check runs actual package execution against a controlled model response
server on localhost. It checks a complete benchmark, an incorrect classification,
and a human review. It requires no model credentials and makes no model-service
requests; it verifies integration rather than model quality.
