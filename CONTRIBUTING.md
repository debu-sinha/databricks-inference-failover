# Contributing

Keep the client small and explicit. Before changing a function, read its callers, tests and example consumers. Update the design record when the failure policy or authentication boundary changes.

Run these checks before proposing a change:

```bash
python -m pip install -e '.[dev,auth]'
python -m ruff format --check .
python -m ruff check .
python -m mypy
python -m pytest -q
python -m inference_failover
```

Add failure tests for new behavior. Local tests must not call a cloud service or read developer credentials. Live tests require explicit targets and authorization, with a sanitized result record. Do not use local tests as evidence of regional recovery.

Have a second reviewer read security boundaries, failure behavior, public imports, docs and tests before publishing. Inspect rendered diagrams and check that they describe the actual implementation. Keep names, workspace identifiers, private messages and credentials out of the repository.

Report a security issue privately to the repository owner. Do not put tokens or sensitive payloads in an issue.
